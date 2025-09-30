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

        # DynamoDB table for storing hands history
        hands_history_table = dynamodb.Table(
            self, "HandsHistoryTable",
            table_name="blackjack-hands-history",
            partition_key=dynamodb.Attribute(
                name="hand_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY
        )

        # Add GSI for querying hands by user_id
        hands_history_table.add_global_secondary_index(
            index_name="user-timestamp-index",
            partition_key=dynamodb.Attribute(
                name="user_id",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp",
                type=dynamodb.AttributeType.NUMBER
            ),
            projection_type=dynamodb.ProjectionType.ALL
        )

        # Add GSI for querying hands by date
        hands_history_table.add_global_secondary_index(
            index_name="date-user-index",
            partition_key=dynamodb.Attribute(
                name="date",
                type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="user_id",
                type=dynamodb.AttributeType.STRING
            ),
            projection_type=dynamodb.ProjectionType.ALL
        )

        # DynamoDB table for storing user chip balances
        user_chips_table = dynamodb.Table(
            self, "UserChipsTable",
            table_name="blackjack-user-chips",
            partition_key=dynamodb.Attribute(
                name="user_id",
                type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY
        )

        # Create WebSocket API construct
        self.websocket_api = BlackjackWebSocketConstruct(
            self, "BlackjackWebSocketApi",
            games_table=games_table,
            hands_history_table=hands_history_table,
            user_chips_table=user_chips_table
        )

        # Output the WebSocket URL
        CfnOutput(
            self, "WebSocketUrl",
            value=self.websocket_api.websocket_url,
            description="WebSocket API URL for real-time blackjack game connections"
        )
