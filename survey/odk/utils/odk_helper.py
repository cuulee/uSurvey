from datetime import date, datetime
import decimal
import os
import zipfile
import pytz
from lxml import etree
from django.http import HttpResponse
from django.conf import settings
from django.shortcuts import render
from django import template
from django.db import transaction
from django.shortcuts import get_object_or_404
from djangohttpdigest.digest import Digestor, parse_authorization_header
from djangohttpdigest.authentication import SimpleHardcodedAuthenticator
from django.utils.translation import ugettext as _
from survey.models import Survey, Interviewer, Household, HouseholdMember, HouseholdHead, Question, Batch, ODKSubmission, ODKGeoPoint, LocationCode, TextAnswer, Answer
from survey.models.surveys import SurveySampleSizeReached
from survey.interviewer_configs import NUMBER_OF_HOUSEHOLD_PER_INTERVIEWER
from survey.odk.utils.log import logger
from survey.tasks import execute
from functools import wraps
from survey.utils.zip import InMemoryZip
from django.contrib.sites.models import Site


OPEN_ROSA_VERSION_HEADER = 'X-OpenRosa-Version'
HTTP_OPEN_ROSA_VERSION_HEADER = 'HTTP_X_OPENROSA_VERSION'
OPEN_ROSA_VERSION = '1.0'
DEFAULT_CONTENT_TYPE = 'text/xml; charset=utf-8'
NEW_OR_OLD_HOUSEHOLD_CHOICE_PATH = '//survey/chooseExistingHousehold'
HOUSEHOLD_SELECT_PATH = '//survey/registeredHousehold/household'
HOUSEHOLD_MEMBER_SELECT_PATH = '//survey/registeredHousehold/householdMember/h{{household_id}}'
HOUSEHOLD_MEMBER_ID_DELIMITER = '_'
MANUAL_HOUSEHOLD_SAMPLE_PATH = '//survey/household/houseNumber'
MANUAL_HOUSEHOLD_MEMBER_PATH = '//survey/household/householdMember'
ANSWER_PATH = '//survey/b{{batch_id}}/q{{question_id}}'
NON_RESP_ANSWER_PATH = '//survey/b{{batch_id}}/qnr{{question_id}}'
INSTANCE_ID_PATH = '//survey/meta/instanceID'
FORM_ID_PATH = '//survey/@id'
ONLY_HOUSEHOLD_PATH = '//survey/onlyHousehold'
HOUSE_REG_FORM_ID_PREFIX = 'hreg'
MULTI_SELECT_XFORM_SEP = ' '
GEOPOINT_XFORM_SEP = ' '
# default content length for submission requests
DEFAULT_CONTENT_LENGTH = 10000000
MAX_DISPLAY_PER_COLLECTOR = 1000


def _get_tree(xml_file):
    return etree.fromstring(xml_file.read())

def _get_nodes(search_path, tree=None, xml_string=None): #either tree or xml_string must be defined
    if tree is None:
        tree = etree.fromstring(xml_string)
    try:
        return tree.xpath(search_path)
    except Exception, ex:
        logger.error('Error retrieving path: %s, Desc: %s' % (search_path, str(ex)))

def only_household_reg(survey_tree):
    flag_nodes = _get_nodes(ONLY_HOUSEHOLD_PATH, tree=survey_tree)
    return (flag_nodes and len(flag_nodes) > 0 and flag_nodes[0].text == '1')

def _get_household_members(survey_tree):
    member_nodes = _get_nodes(MANUAL_HOUSEHOLD_MEMBER_PATH, tree=survey_tree)
    return HouseholdMember.objects.filter(pk__in=[member_node.text for member_node in member_nodes]).all()

def _get_member_attrs(survey_tree):
    member_nodes = _get_nodes('%s/*' % MANUAL_HOUSEHOLD_MEMBER_PATH, tree=survey_tree)
    return dict([(member_node.tag, member_node.text) for member_node in member_nodes])

def _get_household_sample_number(survey_tree):
    return _get_nodes(MANUAL_HOUSEHOLD_SAMPLE_PATH, tree=survey_tree)[0].text

def _choosed_existing_household(survey_tree):
    return _get_nodes(NEW_OR_OLD_HOUSEHOLD_CHOICE_PATH, tree=survey_tree)[0].text == '1'

def _get_selected_household_member(survey_tree):
    household_id = _get_nodes(HOUSEHOLD_SELECT_PATH, tree=survey_tree)[0].text
    context = template.Context({'household_id': household_id})
    hm_path = template.Template(HOUSEHOLD_MEMBER_SELECT_PATH).render(context)    
    member_id = (_get_nodes(hm_path, tree=survey_tree)[0].text).split(HOUSEHOLD_MEMBER_ID_DELIMITER)[0]
    return HouseholdMember.objects.get(pk=member_id)

def _get_or_create_household_member(interviewer, survey, survey_tree):
    if _choosed_existing_household(survey_tree):
        return _get_selected_household_member(survey_tree)
    sample_number = _get_household_sample_number(survey_tree)
    try:
        household = Household.objects.get(interviewer=interviewer, survey=survey, ea=interviewer.ea, random_sample_number=sample_number)
    except Household.DoesNotExist:
        uid = Household.next_uid(survey)
        household_code_value = LocationCode.get_household_code(interviewer) + str(uid)
        household = Household.objects.create(interviewer=interviewer, ea=interviewer.ea,
                                     uid=uid, random_sample_number=sample_number,
                                     survey=survey, household_code=household_code_value)
    #now time for member details
    MALE = '1'
    IS_HEAD = '1'
    mem_attrs = _get_member_attrs(survey_tree)
    kwargs = {}
    kwargs['surname'] = mem_attrs.get('surname')
    kwargs['first_name'] = mem_attrs['firstName']
    kwargs['male'] = (mem_attrs['sex'] == MALE)
    kwargs['date_of_birth'] = datetime.strptime(mem_attrs['dateOfBirth'], '%Y-%m-%d')
    kwargs['household'] = household
    if mem_attrs['isHead'] == IS_HEAD:
        kwargs['occupation'] = mem_attrs.get('occupation', '')
        kwargs['level_of_education'] = mem_attrs.get('levelOfEducation', '')
        resident_since = datetime.strptime(mem_attrs.get('residentSince', '0000-00-00'), '%Y-%m-%d')
        kwargs['resident_since_year']=resident_since.year
        kwargs['resident_since_month']=resident_since.month
        return HouseholdHead.objects.create(**kwargs)
    else:
        return HouseholdMember.objects.create(**kwargs)
    
def build_answer(question, response):
    logger.debug('question: %s, response: %s' % (question.pk, response))
    if isinstance(response, NonResponseAnswer):
        return response
    if question.answer_type == Question.MULTICHOICE:
        return question.options.get(pk=response)
    if question.answer_type == Question.MULTISELECT:
        return question.options.filter(pk__in=response.split(MULTI_SELECT_XFORM_SEP))
    if question.answer_type == Question.DATE:
        return datetime.strptime(response, '%Y-%m-%d')
    if question.answer_type == Question.GEOPOINT:
        answer = ODKGeoPoint()
        (answer.latitude, answer.longitude, answer.altitude, answer.precision) = response.split(GEOPOINT_XFORM_SEP)
        answer.save()
        return answer
    return response

def register_member_answer(interviewer, question, household_member, answer, batch):
    answer_class = question.answer_class()
    answer = build_answer(question, answer)
    if question.answer_type == Question.MULTISELECT and not isinstance(answer, NonResponseAnswer):
        created = answer_class.objects.create(interviewer=interviewer, question=question, householdmember=household_member,
                         household=household_member.household, batch=batch)
        created.answer = answer
        created.save()
    else:
        if isinstance(answer, NonResponseAnswer):
            answer_class = TextAnswer
            answer = answer.answer
        created = answer_class.objects.create(interviewer=interviewer, question=question, householdmember=household_member,
                         answer=answer, household=household_member.household, batch=batch)
    return created

class NonResponseAnswer(Answer):
    '''
    Basically place holder for non response answers. only used to extract the non response text answer
    '''
    answer = ''
    def __init__(self, answer):
        self.answer = answer

def _get_responses(interviewer, survey_tree, survey):
    response_dict = {}
    batches = interviewer.get_open_batch_for_survey(survey)
    for batch in batches:
        for question in batch.all_questions():
            context = template.Context({'batch_id': batch.pk, 'question_id' : question.pk})
            answer_path = template.Template(ANSWER_PATH).render(context)
            resp_text, resp_node = None, _get_nodes(answer_path, tree=survey_tree)
            if resp_node: #if question is relevant but 
                resp_text = resp_node[0].text
                if (not resp_text) and question.group.name == 'NON_RESPONSE': #no response and its a non response question
                    nrsp_answer_path = template.Template(NON_RESP_ANSWER_PATH).render(context)
                    resp_text = NonResponseAnswer(_get_nodes(nrsp_answer_path, tree=survey_tree)[0].text)
            response_dict[(batch.pk, question.pk)] = resp_text
    return response_dict
                
def _get_instance_id(survey_tree):
    return _get_nodes(INSTANCE_ID_PATH, tree=survey_tree)[0].text

def _get_form_id(survey_tree):
    return _get_nodes(FORM_ID_PATH, tree=survey_tree)[0]

def _get_survey(survey_tree):
    pk = _get_nodes(FORM_ID_PATH, tree=survey_tree)[0].strip(HOUSE_REG_FORM_ID_PREFIX)
    return Survey.objects.get(pk=pk)

@transaction.autocommit
def process_submission(interviewer, xml_file, media_files=[], request=None):
    """
    extract surveys and for this xml file and for specified household member
    """
    media_files = dict([(os.path.basename(f.name), f) for f in media_files])
    reports =  []
    survey_tree = _get_tree(xml_file)
    form_id = _get_form_id(survey_tree)
    survey = _get_survey(survey_tree)
    if (not only_household_reg(survey_tree)) and survey.has_sampling and \
            Household.objects.filter(survey=survey, ea=interviewer.ea).count() >= survey.sample_size: #if its not only household registration, make sure sample size is not violated
        #cannot continue if this survey has reached sample size for this ea
        raise SurveySampleSizeReached()
    member = _get_or_create_household_member(interviewer, survey, survey_tree)
    member_completion_report = {}
    response_dict = _get_responses(interviewer, survey_tree, survey)
    treated_batches = {}
    if response_dict and not only_household_reg(survey_tree):
        for (b_id, q_id), answer in response_dict.items():
            question = Question.objects.get(pk=q_id)
            batch = treated_batches.get(b_id, Batch.objects.get(pk=b_id))
            if answer is not None:
                if question.answer_type in [Question.AUDIO, Question.IMAGE, Question.VIDEO]:
                    answer = media_files.get(answer, None)
                created = register_member_answer(interviewer, question, member, answer, batch)
                member_completion_report[(b_id, q_id)] = created
            if b_id not in treated_batches.keys():
                treated_batches[b_id] = batch
        map(lambda batch: member.batch_completed(batch), treated_batches.values()) #create batch completion for question batches
        if member.household.completed_currently_open_batches():
            map(lambda batch: member.household.batch_completed(batch), treated_batches.values())
    submission = ODKSubmission.objects.create(interviewer=interviewer, 
                survey=survey, form_id= form_id,
                instance_id=_get_instance_id(survey_tree), household_member=member, 
                xml=etree.tostring(survey_tree, pretty_print=True))
    #    execute.delay(submission.save_attachments, media_files)
    submission.save_attachments(media_files.values())
    return submission

def get_surveys(interviewer):
    return Survey.currently_open_surveys(interviewer.location)

def get_households(interviewer):
    """
        return the households with uncompleted surveys for households assigned to this interviewer
        #to do: Need to make this retrieval more effecient in the future
    """
    open_surveys = Survey.currently_open_surveys(interviewer.location)
    logger.debug('open surveys: %s' % open_surveys)
    households = []
    for open_survey in open_surveys:
        if open_survey.has_sampling:
#            RandomHouseHoldSelection.objects.get_or_create(mobile_number=interviewer.mobile_number, survey=open_survey)[0].generate(
#                no_of_households=open_survey.sample_size, survey=open_survey)
            households.extend(interviewer.households.filter(ea=interviewer.ea, survey=open_survey, random_sample_number__isnull=False).all())
        else:
            households.extend(interviewer.all_households(open_survey=open_survey, non_response_reporting=True))      
        logger.debug('households: %s' % len(households))
    return [household for household in households if household.has_pending_survey()] 


class SubmissionReport:
    form_id = None
    instance_id = None
    report_details = None

    def __init__(self, form_id, instance_id, report_details):
        self.form_id = form_id
        self.instance_id = instance_id
        self.report_details = report_details

def disposition_ext_and_date(name, extension, show_date=True):
    if name is None:
        return 'attachment;'
    if show_date:
        name = "%s_%s" % (name, date.today().strftime("%Y_%m_%d"))
    return 'attachment; filename=%s.%s' % (name, extension)

def response_with_mimetype_and_name(
        mimetype, name, extension=None, show_date=True, file_path=None,
        use_local_filesystem=False, full_mime=False):
    if extension is None:
        extension = mimetype
    if not full_mime:
        mimetype = "application/%s" % mimetype
    if file_path:
        try:
            if not use_local_filesystem:
                default_storage = get_storage_class()()
                wrapper = FileWrapper(default_storage.open(file_path))
                response = StreamingHttpResponse(wrapper, mimetype=mimetype)
                response['Content-Length'] = default_storage.size(file_path)
            else:
                wrapper = FileWrapper(open(file_path))
                response = StreamingHttpResponse(wrapper, mimetype=mimetype)
                response['Content-Length'] = os.path.getsize(file_path)
        except IOError:
            response = HttpResponseNotFound(
                _(u"The requested file could not be found."))
    else:
        response = HttpResponse(mimetype=mimetype)
    response['Content-Disposition'] = disposition_ext_and_date(
        name, extension, show_date)
    return response


class HttpResponseNotAuthorized(HttpResponse):
    status_code = 401

    def __init__(self):
        HttpResponse.__init__(self)
        self['WWW-Authenticate'] =\
            'Basic realm="%s"' % Site.objects.get_current().name

class BaseOpenRosaResponse(HttpResponse):
    status_code = 201

    def __init__(self, *args, **kwargs):
        super(BaseOpenRosaResponse, self).__init__(*args, **kwargs)

        self[OPEN_ROSA_VERSION_HEADER] = OPEN_ROSA_VERSION
        tz = pytz.timezone(settings.TIME_ZONE)
        dt = datetime.now(tz).strftime('%a, %d %b %Y %H:%M:%S %Z')
        self['Date'] = dt
        self['X-OpenRosa-Accept-Content-Length'] = DEFAULT_CONTENT_LENGTH
        self['Content-Type'] = DEFAULT_CONTENT_TYPE


class OpenRosaResponse(BaseOpenRosaResponse):
    status_code = 201

    def __init__(self, *args, **kwargs):
        super(OpenRosaResponse, self).__init__(*args, **kwargs)
        # wrap content around xml
        self.content = '''<?xml version='1.0' encoding='UTF-8' ?>
<OpenRosaResponse xmlns="http://openrosa.org/http/response">
        <message nature="">%s</message>
</OpenRosaResponse>''' % self.content


class OpenRosaResponseNotFound(OpenRosaResponse):
    status_code = 404


class OpenRosaResponseBadRequest(OpenRosaResponse):
    status_code = 400

class OpenRosaResponseNotAllowed(OpenRosaResponse):
    status_code = 405

class OpenRosaRequestForbidden(OpenRosaResponse):
    status_code = 403

class OpenRosaServerError(OpenRosaResponse):
    status_code = 500

def http_basic_interviewer_auth(func):
    @wraps(func)
    def _decorator(request, *args, **kwargs):
        if request.META.has_key('HTTP_AUTHORIZATION'):
            authmeth, auth = request.META['HTTP_AUTHORIZATION'].split(' ', 1)
            logger.debug('request meta: %s' % request.META['HTTP_AUTHORIZATION'])
            if authmeth.lower() == 'basic':
                auth = auth.strip().decode('base64')
                username, password = auth.split(':', 1)
                try:
                    request.user = Interviewer.objects.get(mobile_number=username, odk_token=password)
                    return func(request, *args, **kwargs)
                except Interviewer.DoesNotExist:
                    return OpenRosaResponseNotFound()
        return HttpResponseNotAuthorized()
    return _decorator

def http_digest_interviewer_auth(func):
    @wraps(func)
    def _decorator(request, *args, **kwargs):
        realm = Site.objects.get_current().name
        digestor = Digestor(method=request.method, path=request.get_full_path(), realm=realm)
        if request.META.has_key('HTTP_AUTHORIZATION'):
            logger.debug('request meta: %s' % request.META['HTTP_AUTHORIZATION'])
            try:
                parsed_header = digestor.parse_authorization_header(request.META['HTTP_AUTHORIZATION'])
                if parsed_header['realm'] == realm:
                    interviewer = Interviewer.objects.get(mobile_number=parsed_header['username'], is_blocked=False)
                    authenticator = SimpleHardcodedAuthenticator(server_realm=realm, server_username=interviewer.mobile_number, server_password=interviewer.odk_token)
                    request.user = interviewer
                    if authenticator.secret_passed(digestor):
                        return func(request, *args, **kwargs)
            except Interviewer.DoesNotExist:
                return OpenRosaResponseNotFound()
            except ValueError, err:
                return OpenRosaResponseBadRequest()
        response = HttpResponseNotAuthorized()
        response['www-authenticate'] = digestor.get_digest_challenge()
        return response
    return _decorator

def get_zipped_dir(dirpath):
    zipf = InMemoryZip()    
    for root, dirs, files in os.walk(dirpath):
        for filename in files:
            f = open(os.path.join(root, filename))
            zipf.append(filename, f.read())
            f.close()
    return zipf.read()
