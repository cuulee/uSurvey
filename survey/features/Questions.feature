Feature: Questions related features

Scenario: List Questions Under a batch
  Given I am logged in as researcher
  And I have a survey
  And I have a batch
  And I have 100 questions under the batch
  And I visit questions listing page of the batch
  Then I should see the questions list paginated

Scenario: Error Message on no question
  Given I am logged in as researcher
  And I have a survey
  And I have a batch
  And I have no questions under the batch
  And I visit questions listing page of the batch
  Then I should see error message on the page

Scenario: Add new question to batch
  Given I am logged in as researcher
  And I have a survey
  And I have a batch
  And I visit questions listing page of the batch
  And I have a member group
  And I click add question button
  Then I should see the assign question page of that batch

Scenario: MultiChoice question
  Given I am logged in as researcher
  And I have a member group
  And I visit create new question page
  And I fill the details for question
  When I select multichoice for answer type
  Then I should see one option field
  When I click add-option icon
  Then I should see two options field
  When I click remove-option icon
  Then I should see only one option field
  And I fill an option question
  And I submit the form
  And I should see question successfully added message

Scenario: List All Questions
  Given I am logged in as researcher
  And I have more than 50 questions
  And I visit questions list page
  Then I should see the questions list paginated
  And If I click create new question link
  Then I should see create new question page