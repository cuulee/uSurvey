from django.test import TestCase
from survey.models import *
from django.db import IntegrityError, DatabaseError
from rapidsms.contrib.locations.models import Location, LocationType
from survey.investigator_configs import *
from django.template.defaultfilters import slugify

class InvestigatorTest(TestCase):

    def test_fields(self):
        investigator = Investigator()
        fields = [str(item.attname) for item in investigator._meta.fields]
        self.assertEqual(len(fields), 12)
        for field in ['id', 'name', 'mobile_number', 'created', 'modified', 'male', 'age', 'level_of_education', 'location_id', 'language', 'backend_id', 'weights']:
            self.assertIn(field, fields)

    def test_store(self):
        investigator = Investigator.objects.create(name="Investigator", mobile_number="987654321", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'), weights=30.99)
        self.failUnless(investigator.id)
        self.failUnless(investigator.created)
        self.failUnless(investigator.modified)
        self.assertEqual(investigator.identity, COUNTRY_PHONE_CODE + investigator.mobile_number)
        self.assertEqual(investigator.weights, 30.99)

    def test_mobile_number_is_unique(self):
        Investigator.objects.create(name="", mobile_number = "123456789", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        self.failUnlessRaises(IntegrityError, Investigator.objects.create, mobile_number = "123456789")

    def test_mobile_number_length_must_be_less_than_10(self):
        mobile_number_of_length_11="01234567891"
        self.failUnlessRaises(DatabaseError, Investigator.objects.create, mobile_number = mobile_number_of_length_11)

    def test_next_answerable_question(self):
        investigator = Investigator.objects.create(name="investigator name", mobile_number="9876543210", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        household = Household.objects.create(investigator=investigator)
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order = 1)
        batch.open_for_location(investigator.location)
        indicator = Indicator.objects.create(batch=batch, order=1)
        question_1 = Question.objects.create(indicator=indicator, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        question_2 = Question.objects.create(indicator=indicator, text="How many of them are male?", answer_type=Question.NUMBER, order=2)

        self.assertEqual(question_1, investigator.next_answerable_question(household))

        NumericalAnswer.objects.create(investigator=investigator, household=household, question=question_1, answer=10)

        self.assertEqual(question_2, investigator.next_answerable_question(household))

        NumericalAnswer.objects.create(investigator=investigator, household=household, question=question_2, answer=10)

        self.assertEqual(None, investigator.next_answerable_question(household))

    def test_location_hierarchy(self):
        country = LocationType.objects.create(name="Country", slug=slugify("country"))
        city = LocationType.objects.create(name="City", slug=slugify("city"))
        uganda = Location.objects.create(name="Uganda", type=country)
        kampala = Location.objects.create(name="Kampala", type=city, tree_parent=uganda)
        investigator = Investigator.objects.create(name="investigator name", mobile_number="9876543210", location = kampala, backend = Backend.objects.create(name='something'))
        self.assertEquals(investigator.location_hierarchy(), {'Country': uganda, 'City': kampala})

class LocationTest(TestCase):

    def test_store(self):
        country = LocationType.objects.create(name='Country',slug='country')
        district = LocationType.objects.create(name='District',slug='district')
        uganda = Location.objects.create(name="Uganda", type=country)
        kampala = Location.objects.create(name="Kampala", type=district, tree_parent=uganda)

        u = Location.objects.get(type__name='Country',name='Uganda')
        report_locations = u.get_descendants(include_self=True).all()
        self.assertEqual(len(report_locations), 2)
        self.assertIn(uganda, report_locations)
        self.assertIn(kampala, report_locations)

class LocationAutoCompleteTest(TestCase):
    def test_store(self):
        self.assertEqual(len(LocationAutoComplete.objects.all()), 0)
        uganda = Location.objects.create(name="Uganda")
        self.assertEqual(len(LocationAutoComplete.objects.all()), 1)
        self.assertEqual(uganda.auto_complete_text(), "Uganda")
        self.assertEqual(LocationAutoComplete.objects.all()[0].text, "Uganda")

        kampala = Location.objects.create(name="Kampala", tree_parent=uganda)
        self.assertEqual(kampala.auto_complete_text(), "Uganda > Kampala")

        soroti = Location.objects.create(name="Soroti", tree_parent=kampala)
        self.assertEqual(soroti.auto_complete_text(), "Uganda > Kampala > Soroti")

        kampala.name = "Kampala Changed"
        kampala.save()
        self.assertEqual(kampala.auto_complete_text(), "Uganda > Kampala Changed")

        soroti = Location.objects.get(name="Soroti")
        self.assertEqual(soroti.auto_complete_text(), "Uganda > Kampala Changed > Soroti")

class SurveyTest(TestCase):
    def test_store(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        self.failUnless(survey.id)

class BatchTest(TestCase):
    def test_store(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order=1, name="Batch name")
        self.failUnless(batch.id)

class IndicatorTest(TestCase):
    def setUp(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        self.batch = Batch.objects.create(survey=survey, order = 1)

    def test_store(self):
        indicator = Indicator.objects.create(batch=self.batch, order=1, identifier="IDENTIFIER")
        self.failUnless(indicator.id)

    def test_order(self):
        indicator_2 = Indicator.objects.create(batch=self.batch, order=2, identifier="IDENTIFIER")
        indicator_1 = Indicator.objects.create(batch=self.batch, order=1, identifier="IDENTIFIER_1")
        indicators = self.batch.indicators.order_by('order').all()
        self.assertEqual(indicators[0], indicator_1)
        self.assertEqual(indicators[1], indicator_2)

class QuestionTest(TestCase):
    def setUp(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order =1)
        self.indicator = Indicator.objects.create(batch=batch, order=1)

    def test_numerical_question(self):
        question = Question.objects.create(indicator=self.indicator, text="This is a question", answer_type=Question.NUMBER)
        self.failUnless(question.id)

    def test_text_question(self):
        question = Question.objects.create(indicator=self.indicator, text="This is a question", answer_type=Question.TEXT)
        self.failUnless(question.id)

    def test_multichoice_question(self):
        question = Question.objects.create(indicator=self.indicator, text="This is a question", answer_type=Question.MULTICHOICE)
        self.failUnless(question.id)

    def test_order(self):
        question_2 = Question.objects.create(indicator=self.indicator, text="This is a question", answer_type="number", order=2)
        question_1 = Question.objects.create(indicator=self.indicator, text="This is another question", answer_type="number", order=1)
        questions = self.indicator.questions.order_by('order').all()
        self.assertEqual(questions[0], question_1)
        self.assertEqual(questions[1], question_2)

class QuestionOptionTest(TestCase):
    def setUp(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order = 1)
        indicator = Indicator.objects.create(batch=batch, order=1)
        self.question = Question.objects.create(indicator=indicator, text="This is a question", answer_type="multichoice")

    def test_store(self):
        option_2 = QuestionOption.objects.create(question=self.question, text="OPTION 1", order=2)
        option_1 = QuestionOption.objects.create(question=self.question, text="OPTION 2", order=1)
        options = self.question.options.order_by('order').all()
        self.assertEqual(len(options), 2)
        options_in_text = "1: %s\n2: %s" % (option_1.text, option_2.text)
        self.assertEqual(self.question.options_in_text(), options_in_text)

    def test_question_text(self):
        option_2 = QuestionOption.objects.create(question=self.question, text="OPTION 1", order=2)
        option_1 = QuestionOption.objects.create(question=self.question, text="OPTION 2", order=1)
        question_in_text = "%s\n%s" % (self.question.text, self.question.options_in_text())
        self.assertEqual(self.question.to_ussd(), question_in_text)

class HouseHoldTest(TestCase):
    def test_store(self):
        self.investigator = Investigator.objects.create(name="Investigator", mobile_number="9876543210", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        self.household = Household.objects.create(investigator=self.investigator)
        self.failUnless(self.household.id)

    def test_has_pending_survey(self):
        investigator = Investigator.objects.create(name="investigator name", mobile_number="9876543210", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        household = Household.objects.create(investigator=investigator)
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order=1)
        indicator = Indicator.objects.create(batch=batch, order=1)
        question_1 = Question.objects.create(indicator=indicator, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        question_2 = Question.objects.create(indicator=indicator, text="How many of them are male?", answer_type=Question.NUMBER, order=2)

        self.assertFalse(household.has_pending_survey())

        NumericalAnswer.objects.create(investigator=investigator, household=household, question=question_1, answer=10)

        self.assertTrue(household.has_pending_survey())

        NumericalAnswer.objects.create(investigator=investigator, household=household, question=question_2, answer=10)

        self.assertFalse(household.has_pending_survey())

    def test_retake_latest_batch(self):
        self.investigator = Investigator.objects.create(name="Investigator", mobile_number="9876543210", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        self.household = Household.objects.create(investigator=self.investigator)

        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch_1 = Batch.objects.create(survey=survey, order = 1)
        indicator_1 = Indicator.objects.create(batch=batch_1, order=1)
        question_1 = Question.objects.create(indicator=indicator_1, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        self.investigator.answered(question_1, self.household, 1)
        batch_1.open_for_location(self.investigator.location)

        batch_2 = Batch.objects.create(survey=survey, order = 2)
        indicator_2 = Indicator.objects.create(batch=batch_2, order=1)
        question_2 = Question.objects.create(indicator=indicator_2, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        self.investigator.answered(question_2, self.household, 1)

        self.assertEquals(NumericalAnswer.objects.count(), 2)

        self.household.retake_latest_batch()

        self.assertEquals(NumericalAnswer.objects.count(), 1)

class NumericalAnswerTest(TestCase):
    def test_store(self):
        investigator = Investigator.objects.create(name="Investigator", mobile_number="9876543210", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        household = Household.objects.create( investigator=investigator)
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order=1)
        indicator = Indicator.objects.create(batch=batch, order=1)
        question = Question.objects.create(indicator=indicator, text="This is a question", answer_type=Question.NUMBER)

        answer = NumericalAnswer.objects.create(investigator=investigator, household=household, question=question, answer=10)
        self.failUnless(answer.id)

class TextAnswerTest(TestCase):
    def test_store(self):
        investigator = Investigator.objects.create(name="Investigator", mobile_number="9876543210", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        household = Household.objects.create(investigator=investigator)
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order=1)
        indicator = Indicator.objects.create(batch=batch, order=1)
        question = Question.objects.create(indicator=indicator, text="This is a question", answer_type=Question.TEXT)

        answer = TextAnswer.objects.create(investigator=investigator, household=household, question=question, answer="This is an answer")
        self.failUnless(answer.id)

class MultiChoiceAnswerTest(TestCase):
    def test_store(self):
        investigator = Investigator.objects.create(name="Investigator", mobile_number="9876543210", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        household = Household.objects.create(investigator=investigator)
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order=1)
        indicator = Indicator.objects.create(batch=batch, order=1)
        question = Question.objects.create(indicator=indicator, text="This is a question", answer_type=Question.MULTICHOICE)
        option = QuestionOption.objects.create(question=question, text="This is an option")

        answer = MultiChoiceAnswer.objects.create(investigator=investigator, household=household, question=question, answer=option)
        self.failUnless(answer.id)

    def test_pagination(self):
        investigator = Investigator.objects.create(name="Investigator", mobile_number="9876543210", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        household = Household.objects.create( investigator=investigator)
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order=1)
        indicator = Indicator.objects.create(batch=batch, order=1)
        question = Question.objects.create(indicator=indicator, text="This is a question", answer_type=Question.MULTICHOICE)
        option_1 = QuestionOption.objects.create(question=question, text="OPTION 1", order=1)
        option_2 = QuestionOption.objects.create(question=question, text="OPTION 2", order=2)
        option_3 = QuestionOption.objects.create(question=question, text="OPTION 3", order=3)
        option_4 = QuestionOption.objects.create(question=question, text="OPTION 4", order=4)
        option_5 = QuestionOption.objects.create(question=question, text="OPTION 5", order=5)
        option_6 = QuestionOption.objects.create(question=question, text="OPTION 6", order=6)
        option_7 = QuestionOption.objects.create(question=question, text="OPTION 7", order=7)
        back_text = Question.PREVIOUS_PAGE_TEXT
        next_text = Question.NEXT_PAGE_TEXT

        question_in_text = "%s\n1: %s\n2: %s\n3: %s\n%s" % (question.text, option_1.text, option_2.text, option_3.text, next_text)
        self.assertEqual(question.to_ussd(), question_in_text)

        question_in_text = "%s\n1: %s\n2: %s\n3: %s\n%s" % (question.text, option_1.text, option_2.text, option_3.text, next_text)
        self.assertEqual(question.to_ussd(1), question_in_text)

        question_in_text = "%s\n4: %s\n5: %s\n6: %s\n%s\n%s" % (question.text, option_4.text, option_5.text, option_6.text, back_text, next_text)
        self.assertEqual(question.to_ussd(2), question_in_text)

        question_in_text = "%s\n7: %s\n%s" % (question.text, option_7.text, back_text)
        self.assertEqual(question.to_ussd(3), question_in_text)


class AnswerRuleTest(TestCase):
    def setUp(self):
        self.investigator = Investigator.objects.create(name="Investigator", mobile_number="9876543210", location = Location.objects.create(name="Kampala"), backend = Backend.objects.create(name='something'))
        self.household = Household.objects.create(investigator=self.investigator)
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order=1)
        self.indicator = Indicator.objects.create(batch=batch, order=1)

    def test_numerical_equals_and_end_rule(self):
        NumericalAnswer.objects.all().delete()
        question_1 = Question.objects.create(indicator=self.indicator, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        question_2 = Question.objects.create(indicator=self.indicator, text="How many of them are male?", answer_type=Question.NUMBER, order=2)

        next_question = self.investigator.answered(question_1, self.household, answer=1)
        self.assertEqual(next_question, question_2)

        NumericalAnswer.objects.all().delete()
        rule = AnswerRule.objects.create(question=question_1, action=AnswerRule.ACTIONS['END_INTERVIEW'], condition=AnswerRule.CONDITIONS['EQUALS'], validate_with_value=0)

        next_question = self.investigator.answered(question_1, self.household, answer=0)
        self.assertEqual(next_question, question_1)

        next_question = self.investigator.answered(question_1, self.household, answer=0)
        self.assertEqual(next_question, None)

    def test_numerical_equals_and_skip_to_rule(self):
        NumericalAnswer.objects.all().delete()
        question_1 = Question.objects.create(indicator=self.indicator, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        question_2 = Question.objects.create(indicator=self.indicator, text="How many of them are male?", answer_type=Question.NUMBER, order=2)
        question_3 = Question.objects.create(indicator=self.indicator, text="How many of them are male?", answer_type=Question.NUMBER, order=3)

        next_question = self.investigator.answered(question_1, self.household, answer=1)
        self.assertEqual(next_question, question_2)

        NumericalAnswer.objects.all().delete()
        rule = AnswerRule.objects.create(question=question_1, action=AnswerRule.ACTIONS['SKIP_TO'], condition=AnswerRule.CONDITIONS['EQUALS'], validate_with_value=0, next_question=question_3)

        next_question = self.investigator.answered(question_1, self.household, answer=0)
        self.assertEqual(next_question, question_3)

    def test_numerical_greater_than_value_and_reanswer(self):
        NumericalAnswer.objects.all().delete()
        question_0 = Question.objects.create(indicator=self.indicator, text="How are you?", answer_type=Question.NUMBER, order=0)
        question_1 = Question.objects.create(indicator=self.indicator, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        rule = AnswerRule.objects.create(question=question_1, action=AnswerRule.ACTIONS['REANSWER'], condition=AnswerRule.CONDITIONS['GREATER_THAN_VALUE'], validate_with_value=4)

        next_question = self.investigator.answered(question_0, self.household, answer=5)

        self.assertEqual(NumericalAnswer.objects.count(), 1)
        next_question = self.investigator.answered(question_1, self.household, answer=5)
        self.assertEqual(next_question, question_1)
        self.assertEqual(NumericalAnswer.objects.count(), 1)

        next_question = self.investigator.answered(question_1, self.household, answer=4)
        self.assertEqual(next_question, None)
        self.assertEqual(NumericalAnswer.objects.count(), 2)


    def test_numerical_greater_than_question_and_reanswer(self):
        NumericalAnswer.objects.all().delete()
        question_1 = Question.objects.create(indicator=self.indicator, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        question_2 = Question.objects.create(indicator=self.indicator, text="How many of them are male?", answer_type=Question.NUMBER, order=2)
        question_3 = Question.objects.create(indicator=self.indicator, text="How many of them are children?", answer_type=Question.NUMBER, order=3)

        rule = AnswerRule.objects.create(question=question_2, action=AnswerRule.ACTIONS['REANSWER'], condition=AnswerRule.CONDITIONS['GREATER_THAN_QUESTION'], validate_with_question=question_1)

        self.assertEqual(NumericalAnswer.objects.count(), 0)
        next_question = self.investigator.answered(question_1, self.household, answer=1)
        self.assertEqual(next_question, question_2)
        self.assertEqual(NumericalAnswer.objects.count(), 1)

        next_question = self.investigator.answered(question_2, self.household, answer=10)
        self.assertEqual(next_question, question_1)
        self.assertEqual(NumericalAnswer.objects.count(), 0)

    def test_numerical_less_than_value_and_reanswer(self):
        NumericalAnswer.objects.all().delete()
        question_0 = Question.objects.create(indicator=self.indicator, text="How are you?", answer_type=Question.NUMBER, order=0)
        question_1 = Question.objects.create(indicator=self.indicator, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        rule = AnswerRule.objects.create(question=question_1, action=AnswerRule.ACTIONS['REANSWER'], condition=AnswerRule.CONDITIONS['LESS_THAN_VALUE'], validate_with_value=4)

        next_question = self.investigator.answered(question_0, self.household, answer=5)

        self.assertEqual(NumericalAnswer.objects.count(), 1)
        next_question = self.investigator.answered(question_1, self.household, answer=3)
        self.assertEqual(next_question, question_1)
        self.assertEqual(NumericalAnswer.objects.count(), 1)

        next_question = self.investigator.answered(question_1, self.household, answer=4)
        self.assertEqual(next_question, None)
        self.assertEqual(NumericalAnswer.objects.count(), 2)


    def test_numerical_less_than_question_and_reanswer(self):
        NumericalAnswer.objects.all().delete()
        question_1 = Question.objects.create(indicator=self.indicator, text="How many members are there in this household?", answer_type=Question.NUMBER, order=1)
        question_2 = Question.objects.create(indicator=self.indicator, text="How many of them are male?", answer_type=Question.NUMBER, order=2)
        question_3 = Question.objects.create(indicator=self.indicator, text="How many of them are children?", answer_type=Question.NUMBER, order=3)

        rule = AnswerRule.objects.create(question=question_2, action=AnswerRule.ACTIONS['REANSWER'], condition=AnswerRule.CONDITIONS['LESS_THAN_QUESTION'], validate_with_question=question_1)

        self.assertEqual(NumericalAnswer.objects.count(), 0)
        next_question = self.investigator.answered(question_1, self.household, answer=10)
        self.assertEqual(next_question, question_2)
        self.assertEqual(NumericalAnswer.objects.count(), 1)

        next_question = self.investigator.answered(question_2, self.household, answer=9)
        self.assertEqual(next_question, question_1)
        self.assertEqual(NumericalAnswer.objects.count(), 0)

    def test_multichoice_equals_option_and_ask_sub_question(self):
        question_1 = Question.objects.create(indicator=self.indicator, text="How many members are there in this household?", answer_type=Question.MULTICHOICE, order=1)
        option_1_1 = QuestionOption.objects.create(question=question_1, text="OPTION 1", order=1)
        option_1_2 = QuestionOption.objects.create(question=question_1, text="OPTION 2", order=2)

        sub_question_1 = Question.objects.create(indicator=self.indicator, text="Specify others", answer_type=Question.TEXT, subquestion=True, parent=question_1)

        question_2 = Question.objects.create(indicator=self.indicator, text="How many of them are male?", answer_type=Question.NUMBER, order=2)

        rule = AnswerRule.objects.create(question=question_1, action=AnswerRule.ACTIONS['ASK_SUBQUESTION'], condition=AnswerRule.CONDITIONS['EQUALS_OPTION'], validate_with_option=option_1_2, next_question=sub_question_1)

        next_question = self.investigator.answered(question_1, self.household, answer=1)
        self.assertEqual(next_question, question_2)

        MultiChoiceAnswer.objects.all().delete()

        next_question = self.investigator.answered(question_1, self.household, answer=2)
        self.assertEqual(next_question, sub_question_1)

        next_question = self.investigator.answered(sub_question_1, self.household, answer="Some explanation")
        self.assertEqual(next_question, question_2)

class BatchLocationStatusTest(TestCase):

    def test_store(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch_1 = Batch.objects.create(survey=survey, order=1)
        kampala = Location.objects.create(name="Kampala")
        batch_location_status = BatchLocationStatus.objects.create(batch=batch_1, location=kampala)
        self.failUnless(batch_location_status.id)

    def test_open_and_close_for_location(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch_1 = Batch.objects.create(survey=survey, order=1)
        batch_2 = Batch.objects.create(survey=survey, order=2)
        kampala = Location.objects.create(name="Kampala")
        abim = Location.objects.create(name="Abim")
        investigator_1 = Investigator.objects.create(name="Investigator 1", mobile_number="1", location=kampala, backend = Backend.objects.create(name='something'))
        investigator_2 = Investigator.objects.create(name="Investigator 2", mobile_number="2", location=abim, backend = Backend.objects.create(name='something1'))

        self.assertEqual(len(investigator_1.get_open_batch()), 0)
        self.assertEqual(len(investigator_2.get_open_batch()), 0)

        batch_1.open_for_location(kampala)
        batch_2.open_for_location(abim)

        self.assertEqual(investigator_1.get_open_batch(), [batch_1])
        self.assertEqual(investigator_2.get_open_batch(), [batch_2])

        batch_1.close_for_location(kampala)
        batch_2.close_for_location(abim)

        self.assertEqual(len(investigator_1.get_open_batch()), 0)
        self.assertEqual(len(investigator_2.get_open_batch()), 0)

class HouseholdBatchCompletionTest(TestCase):
    def test_store(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order=1)
        kampala = Location.objects.create(name="Kampala")
        investigator = Investigator.objects.create(name="Investigator 1", mobile_number="1", location=kampala, backend = Backend.objects.create(name='something'))
        household = Household.objects.create(investigator=investigator)

        batch_completion = HouseholdBatchCompletion.objects.create(household=household, investigator=investigator, batch=batch)
        self.failUnless(batch_completion.id)

    def test_completed(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        batch = Batch.objects.create(survey=survey, order=1)
        kampala = Location.objects.create(name="Kampala")
        investigator = Investigator.objects.create(name="Investigator 1", mobile_number="1", location=kampala, backend = Backend.objects.create(name='something'))
        household = Household.objects.create(investigator=investigator)

        self.assertFalse(household.has_completed_batch(batch))

        household.batch_completed(batch)

        self.assertTrue(household.has_completed_batch(batch))

        household.batch_reopen(batch)

        self.assertFalse(household.has_completed_batch(batch))

class RandomHouseHoldSelectionTest(TestCase):
    def test_store(self):
        selection = RandomHouseHoldSelection.objects.create(mobile_number="123456789", no_of_households=50, selected_households="1,2,3,4,5,6,7,8,9,10")
        self.failUnless(selection.id)

class FormulaTest(TestCase):
    def setUp(self):
        survey = Survey.objects.create(name='Survey Name', description='Survey description')
        self.batch = Batch.objects.create(order=1, survey=survey)
        self.question_1 = Question.objects.create(indicator=Indicator.objects.create(batch=self.batch, order=1), text="Question 1?", answer_type=Question.NUMBER, order=1)
        self.question_2 = Question.objects.create(indicator=Indicator.objects.create(batch=self.batch, order=2), text="Question 2?", answer_type=Question.NUMBER, order=1)

    def test_store(self):
        formula = Formula.objects.create(name="Name", numerator=self.question_1, denominator=self.question_2)
        self.failUnless(formula.id)

    def test_compute_numerical_answers(self):
        uganda = Location.objects.create(name="Uganda")
        kampala = Location.objects.create(name="Kampala", tree_parent=uganda)
        abim = Location.objects.create(name="Abim", tree_parent=uganda)
        backend = Backend.objects.create(name='something')
        investigator = Investigator.objects.create(name="Investigator 1", mobile_number="1", location=kampala, backend = backend, weights = 0.3)
        household_1 = Household.objects.create(investigator=investigator)
        household_2 = Household.objects.create(investigator=investigator)

        investigator_1 = Investigator.objects.create(name="Investigator 2", mobile_number="2", location=abim, backend = backend, weights = 0.9)
        household_3 = Household.objects.create(investigator=investigator_1)
        household_4 = Household.objects.create(investigator=investigator_1)

        formula = Formula.objects.create(name="Name", numerator=self.question_1, denominator=self.question_2)
        investigator.answered(self.question_1, household_1, 20)
        investigator.answered(self.question_2, household_1, 200)
        investigator.answered(self.question_1, household_2, 10)
        investigator.answered(self.question_2, household_2, 100)

        investigator_1.answered(self.question_1, household_3, 40)
        investigator_1.answered(self.question_2, household_3, 400)
        investigator_1.answered(self.question_1, household_4, 50)
        investigator_1.answered(self.question_2, household_4, 500)

        self.assertEquals(formula.compute_for_location(kampala), 3)
        self.assertEquals(formula.compute_for_location(abim), 9)
        self.assertEquals(formula.compute_for_location(uganda), 6)
