from aws_cdk import (
    Duration,
    RemovalPolicy,
    BundlingOptions,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigatewayv2,
    aws_apigatewayv2_integrations as apigatewayv2_integrations,
    aws_iam as iam,
    aws_logs as logs,
)
from constructs import Construct


class BlackjackWebSocketConstruct(Construct):
    """
    WebSocket API construct for real-time Blackjack game server
    """

    def __init__(self, scope: Construct, construct_id: str, games_table: dynamodb.Table, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.games_table = games_table

        # Create WebSocket sessions table for connection management
        self.sessions_table = dynamodb.Table(
            self, "WebSocketSessionsTable",
            table_name="blackjack-websocket-sessions",
            partition_key=dynamodb.Attribute(
                name="connection_id",
                type=dynamodb.AttributeType.STRING
            ),
            time_to_live_attribute="ttl",
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY
        )

        # Add GSI for game_id lookups (to find all connections in a game)
        self.sessions_table.add_global_secondary_index(
            index_name="game-id-index",
            partition_key=dynamodb.Attribute(
                name="game_id",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL
        )

        # Create the main WebSocket handler Lambda
        self.websocket_handler = _lambda.Function(
            self, "WebSocketHandler",
            function_name="blackjack-websocket-handler-prod",
            runtime=_lambda.Runtime.PYTHON_3_11,
            handler="websocket_handler.handler",
            code=_lambda.Code.from_asset(
                ".",
                bundling=BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash", "-c",
                        "pip install boto3 -t /asset-output && "
                        "cp -au lambda_handlers/* /asset-output/"
                    ],
                )
            ),
            architecture=_lambda.Architecture.ARM_64,
            timeout=Duration.seconds(30),
            environment={
                "GAMES_TABLE_NAME": self.games_table.table_name,
                "SESSIONS_TABLE_NAME": self.sessions_table.table_name,
            },
            log_retention=logs.RetentionDays.ONE_WEEK
        )

        # Grant permissions to the WebSocket handler
        self.games_table.grant_read_write_data(self.websocket_handler)
        self.sessions_table.grant_read_write_data(self.websocket_handler)

        # Create integrations
        websocket_integration = apigatewayv2_integrations.WebSocketLambdaIntegration(
            "WebSocketIntegration",
            self.websocket_handler
        )

        # Create the WebSocket API with route options
        self.websocket_api = apigatewayv2.WebSocketApi(
            self, "BlackjackWebSocketApi",
            api_name="Blackjack WebSocket API",
            description="Real-time WebSocket API for Blackjack game",
            connect_route_options=apigatewayv2.WebSocketRouteOptions(
                integration=websocket_integration
            ),
            disconnect_route_options=apigatewayv2.WebSocketRouteOptions(
                integration=websocket_integration
            ),
            default_route_options=apigatewayv2.WebSocketRouteOptions(
                integration=websocket_integration
            )
        )

        # Create WebSocket stage
        self.websocket_stage = apigatewayv2.WebSocketStage(
            self, "WebSocketStage",
            web_socket_api=self.websocket_api,
            stage_name="prod",
            auto_deploy=True
        )

        # Grant API Gateway management permissions for sending messages
        self.websocket_handler.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "execute-api:ManageConnections",
                    "execute-api:Invoke",
                    "lambda:Invoke",
                    "logs:*"
                ],
                resources=[
                    f"*"
                ]
            )
        )

        self.websocket_handler.grant_invoke(
            iam.ServicePrincipal(
                "apigateway.amazonaws.com",
                conditions={
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:execute-api:{self.websocket_api.env.region}:{self.websocket_api.env.account}:{self.websocket_api.api_id}/*/*"
                    }
                }
            )
        )

        # Create CloudWatch Log Group for WebSocket API
        log_group = logs.LogGroup(
            self, "WebSocketApiLogGroup",
            log_group_name=f"/aws/apigateway/{self.websocket_api.api_id}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY
        )

        # Update environment with WebSocket URL
        self.websocket_handler.add_environment("WEBSOCKET_API_ENDPOINT", self.websocket_stage.url)

    @property
    def websocket_url(self) -> str:
        """Get the WebSocket API URL"""
        return self.websocket_stage.url