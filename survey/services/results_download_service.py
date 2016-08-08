from survey.models import LocationTypeDetails, Location, LocationType, Household, HouseholdMember, \
    HouseholdMemberGroup, Answer, MultiChoiceAnswer, MultiSelectAnswer, NumericalAnswer, QuestionOption, Interview
from survey.utils.views_helper import get_ancestors
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from datetime import datetime
import csv, StringIO, string
from collections import OrderedDict
import dateutils
from survey.odk.utils.log import logger


class ResultComposer:
    def __init__(self, user, results_download_service):
        self.results_download_service = results_download_service
        self.user = user

    def send_mail(self):
        attachment_name = '%s.csv' % (self.results_download_service.batch.name if self.results_download_service.batch  \
        else self.results_download_service.survey.name)
        subject = 'Completion report for %s'  % attachment_name
        text = 'Completion report for %s. Date: %s'  % (attachment_name, datetime.now())
        print 'commencing...'
        try:
            mail = EmailMessage(subject, text, settings.DEFAULT_EMAIL_SENDER, [self.user.email, ])
            data = self.results_download_service.generate_interview_reports()
            #data = [[unicode('"%s"' % entry) for entry in entries] for entries in data]
            f = StringIO.StringIO()
            writer = csv.writer(f)
            map(lambda row: writer.writerow(row), data)
            #data = [','.join([unicode('"%s"' % entry) for entry in entries]) for entries in data]
            f.seek(0)
            mail.attach(attachment_name, f.read(), 'text/csv')
            f.close()
            sent = mail.send()
            print 'Emailed!! ', sent
        except Exception, ex:
            print 'error while sending mail: %s', str(ex)



class ResultsDownloadService(object):
    AS_TEXT = 1
    AS_LABEL = 0
    answers = None
    # MEMBER_ATTRS = {
    #     'id' : 'Household ID',
    #      'name' : 'Name', 'Age', 'Date of Birth', 'Gender'
    # }
    def __init__(self, survey=None, batch=None, restrict_to=None, specific_households=None, multi_display=AS_TEXT):
        self.batch = batch
        self.survey, self.questions = self._set_survey_and_questions(survey)
        self.locations = []
        if restrict_to:
            map(lambda loc: self.locations.extend(loc.get_leafnodes(include_self=True)), restrict_to)
        self.specific_households = specific_households
        self.multi_display = int(multi_display)

    def _set_survey_and_questions(self, survey):
        if self.batch:
            return self.batch.survey, self.batch.survey_questions
        survey_questions = []
        map(lambda batch: survey_questions.extend(list(batch.survey_questions)), survey.batches.all())
        return survey, survey_questions

    def set_report_headers(self):
        header = [loc.name for loc in LocationType.objects.exclude(name__iexact="country")]

        other_headers = ['EA', 'Household Number', 'Family Name', 'First Name',  'Age', 'Date of Birth', 'Gender']
        header.extend(other_headers)
        header.extend(self.question_headers())
        return header

    def question_headers(self):
        header = []
        # loop_starters = self.batch.loop_starters()
        for question in self.questions:
        #     if question in loop_starters:
        #         boundary = question.loop_boundary()
        #         loop_questions = self.batch.loop_backs_questions()[boundary]
        #         for i in range(settings.LOOP_QUESTION_REPORT_DEPT-1):
        #             map(lambda q: header.append(q.identifier), loop_questions)
            header.append(question.identifier)
        return header

    def get_summarised_answers(self):
        data = []
        q_opts = {}
        if self.specific_households is None:
            all_households = Household.objects.filter(listing__survey_houselistings__survey=self.survey)
        else:
            all_households = Household.objects.filter(pk__in=self.specific_households,
                                                      listing__survey_houselistings__survey=self.survey)
        locations = list(set(all_households.values_list('listing__ea__locations', flat=True)))
        for location_id in locations:
            households_in_location = all_households.filter(listing__ea__locations=location_id)
            household_location = Location.objects.get(id=location_id)
            location_ancestors = household_location.get_ancestors(include_self=True).\
                exclude(parent__isnull='country').values_list('name', flat=True)
            answers = []
            for household in households_in_location:
                for member in household.members.all():
                    try:
                        answers = list(location_ancestors)
                        member_gender = 'Male' if member.gender == HouseholdMember.MALE else 'Female'
                        answers.extend([household.listing.ea.name, household.house_number, '%s-%s' %
                                        (member.surname, member.first_name), str(member.age),
                                             member.date_of_birth.strftime(settings.DATE_FORMAT),
                                             member_gender])
                        for question in self.questions:
                            reply = member.reply(question)
                            if question.answer_type in [MultiChoiceAnswer.choice_name(),
                                                        MultiSelectAnswer.choice_name()]\
                                    and self.multi_display == self.AS_LABEL:
                                label = q_opts.get((question.pk, reply), None)
                                if label is None:
                                    try:
                                        label = question.options.get(text__iexact=reply).order
                                    except QuestionOption.DoesNotExist:
                                        label = reply
                                    q_opts[(question.pk, reply)] = label
                                reply = str(label)
                            answers.append(reply.encode('utf8'))
                        data.append(answers)
                    except Exception, ex:
                        print 'Error ', str(ex)
        return data

    def get_interview_answers(self):
        report = []
        member_reports = OrderedDict()
        val_list_args = [  'interview__ea__locations__name',
                         'interview__ea__name', 'interview__householdmember__household__house_number',
                         'interview__householdmember__surname', 'interview__householdmember__first_name',
                         'interview__householdmember__date_of_birth', 'interview__householdmember__gender', ]
        parent_loc = 'interview__ea__locations'
        for i in range(LocationType.objects.count() - 2):
            parent_loc = '%s__parent' % parent_loc
            val_list_args.insert(0, '%s__name'%parent_loc)
        filter_args = {}
        if self.locations:
            filter_args['interview__ea__locations__in'] = self.locations
        if self.specific_households:
            filter_args['interview__householdmember__household__in'] = self.specific_households
        for answer_type in Answer.answer_types():
            query_args = list(val_list_args)
            value = 'value'
            if answer_type in [MultiChoiceAnswer.choice_name(), MultiSelectAnswer.choice_name()]:
                value = 'value__text'
                if  self.multi_display == self.AS_LABEL:
                    value = 'value__order'
            query_args.append(value)
            answer_class = Answer.get_class(answer_type)
            # print 'using query_args ', query_args
            answer_data = answer_class.objects.filter(interview__batch=self.batch, **filter_args).\
                values_list('interview__householdmember__pk', 'question__pk', *query_args).\
                        order_by('interview__ea__locations', 'interview__ea',
                                 'interview__householdmember__household', 'interview__householdmember__pk',
                                 'pk', 'loop_id')
                                                    # .distinct(
                                                    #                         'interview__ea__locations',
                                                    #                         'interview__ea',
                                                    #                         'interview__householdmember__household',
                                                    #                         #'interview__householdmember__pk',
                                                    #                         #'question__pk'
                                                    #                        )

            answer_data = list(answer_data)
            # print 'answer data ', len(answer_data)
            #now grab member reports
            for data in answer_data:
                hm_pk, question_pk = data[:2]
                report_data = list(data[2:])
                hm_data = member_reports.get(hm_pk, None)
                if hm_data is None:
                    report_data.insert(-3, str(dateutils.relativedelta(datetime.utcnow().date(),
                                                                       report_data[-3]).years))
                    report_data[-3] = report_data[-3].strftime(settings.DATE_FORMAT)
                    report_data[-2] = 'M' if report_data[-2] else 'F'
                    member_details = [ unicode(md).encode('utf8') for md in report_data[:-1]]
                    hm_data = OrderedDict([('mem_details' , member_details), ])
                hm_question_data = hm_data.get(question_pk, [])
                hm_question_data.append(unicode(report_data[-1]).encode('utf8'))
                hm_data[question_pk] =  hm_question_data
                member_reports[hm_pk] = hm_data

        for hm in member_reports.values():
            answers = hm.pop('mem_details', [])
            #for question_pk, response_data in hm.items():
            loop_starters = self.batch.loop_starters()
            loop_enders = self.batch.loop_enders()
            started = False
            dept = 0
            for question in self.questions:
                # loop_extras = []
                # boundary = question.loop_boundary()
                # if question in loop_starters:
                #     loop_extras = []
                #     loop_questions = self.batch.loop_backs_questions()[boundary]
                #     for i in range(1, settings.LOOP_QUESTION_REPORT_DEPT):
                #         for q in loop_questions:
                #             question_responses = hm.get(question.pk, [])
                #             if len(question_responses) > i:
                #                 resp = question_responses[i]
                #             else:
                #                 resp = ''
                #             loop_extras.append(resp)
                #     import pdb; pdb.set_trace()
                # if question in loop_enders:
                #     answers.extend(loop_extras)
                answers.append(' > '.join(hm.get(question.pk, ['', ])))
            report.append(answers)
        return report


    def generate_report(self):
        data = [self.set_report_headers(), ]
        data.extend(self.get_summarised_answers())
        return data

    def generate_interview_reports(self):
        data = [self.set_report_headers(), ]
        data.extend(self.get_interview_answers())
        return data

    def _get_ancestors_names(self, household_location, exclude_type='country'):
        location_ancestors = get_ancestors(household_location, include_self=True)
        if exclude_type:
            exclude_location = Location.objects.filter(type__name__iexact=exclude_type.lower())
            for location in exclude_location:
                location_ancestors.remove(location)
        result= [ancestor.name for ancestor in location_ancestors]
        result.reverse()
        return result