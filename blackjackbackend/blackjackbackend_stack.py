from aws_cdk import (
    Duration,
    Stack,
    RemovalPolicy,
    CfnOutput,
    aws_dynamodb as dynamodb,
)
from constructs import Construct
from .blackjack_websocket_construct import BlackjackWebSocketConstruct


class BlackjackbackendStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # DynamoDB table for storing game state
        games_table = dynamodb.Table(
            self, "GamesTable",
            table_name="blackjack-games",
            partition_key=dynamodb.Attribute(
                name="game_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY
        )

        # Add Global Secondary Index for game visibility (for future matchmaking if needed)
        games_table.add_global_secondary_index(
            index_name="visibility-status-index",
            partition_key=dynamodb.Attribute(
                name="visibility",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="game_status",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL
        )

        # Create WebSocket API construct
        self.websocket_api = BlackjackWebSocketConstruct(
            self, "BlackjackWebSocketApi",
            games_table=games_table
        )

        # Output the WebSocket URL
        CfnOutput(
            self, "WebSocketUrl",
            value=self.websocket_api.websocket_url,
            description="WebSocket API URL for real-time blackjack game connections"
        )
