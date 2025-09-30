import aws_cdk as core
import aws_cdk.assertions as assertions

from blackjackbackend.blackjackbackend_stack import BlackjackbackendStack

# example tests. To run these tests, uncomment this file along with the example
# resource in blackjackbackend/blackjackbackend_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = BlackjackbackendStack(app, "blackjackbackend")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
