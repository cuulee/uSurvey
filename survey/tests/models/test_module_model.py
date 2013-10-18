from survey.models import QuestionModule
from survey.tests.base_test import BaseTest


class QuestionModuleTest(BaseTest):

    def test_fields(self):
        question_module = QuestionModule()
        fields = [str(item.attname) for item in question_module._meta.fields]
        self.assertEqual(5, len(fields))
        for field in ['id', 'created', 'modified', 'name', 'description']:
            self.assertIn(field, fields)

    def test_store(self):
        module = QuestionModule.objects.create(name="Health", description="some description")
        self.failUnless(module.id)
        self.failUnless(module.name)
        self.failUnless(module.description)