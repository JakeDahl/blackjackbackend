import json
import os
import time
import boto3
from botocore.exceptions import ClientError
from typing import Dict
from decimal import Decimal

# Import service classes
from session_manager import SessionManager
from websocket_utils import WebSocketUtils
from game_service import GameService

# Initialize DynamoDB and API Gateway clients
dynamodb = boto3.resource('dynamodb')
games_table = None
sessions_table = None
hands_history_table = None
user_chips_table = None
apigateway_client = None
session_manager = None
ws_utils = None
game_service = None


def handler(event, context):
    """
    WebSocket handler for real-time blackjack gameplay
    """
    try:
        global games_table, sessions_table, hands_history_table, user_chips_table, apigateway_client
        global session_manager, ws_utils, game_service

        # Initialize tables and client on first use
        if games_table is None:
            games_table = dynamodb.Table(os.environ.get('GAMES_TABLE_NAME', 'blackjack-games'))
        if sessions_table is None:
            sessions_table = dynamodb.Table(os.environ.get('SESSIONS_TABLE_NAME', 'blackjack-websocket-sessions'))
        if hands_history_table is None:
            hands_history_table = dynamodb.Table(os.environ.get('HANDS_HISTORY_TABLE_NAME', 'blackjack-hands-history'))
        if user_chips_table is None:
            user_chips_table = dynamodb.Table(os.environ.get('USER_CHIPS_TABLE_NAME', 'blackjack-user-chips'))

        # Create API Gateway management client with correct endpoint
        if apigateway_client is None:
            domain_name = event['requestContext']['domainName']
            stage = event['requestContext']['stage']
            endpoint_url = f"https://{domain_name}/{stage}"
            apigateway_client = boto3.client('apigatewaymanagementapi', endpoint_url=endpoint_url)

        # Initialize service objects
        if session_manager is None:
            session_manager = SessionManager(sessions_table)
        if ws_utils is None:
            ws_utils = WebSocketUtils(apigateway_client)
        if game_service is None:
            game_service = GameService(games_table, session_manager, ws_utils, hands_history_table, user_chips_table)

        connection_id = event['requestContext']['connectionId']
        route_key = event['requestContext']['routeKey']

        print(f"WebSocket event - Connection: {connection_id}, Route: {route_key}")

        # Handle connection lifecycle events
        if route_key == '$connect':
            return handle_connect(connection_id)
        elif route_key == '$disconnect':
            return handle_disconnect(connection_id)
        elif route_key == '$default':
            return handle_default_message(event, connection_id)
        else:
            return send_error(connection_id, f"Unknown route: {route_key}")

    except Exception as e:
        print(f"WebSocket handler error: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")

        try:
            send_error(connection_id, f"Handler error: {str(e)}")
        except:
            pass
        return {'statusCode': 500}


def handle_connect(connection_id: str) -> Dict:
    """Handle new WebSocket connection"""
    try:
        session_manager.create_session(connection_id)
        print(f"WebSocket connection established: {connection_id}")
        return {'statusCode': 200}
    except Exception as e:
        print(f"Connect error: {str(e)}")
        return {'statusCode': 500}


def handle_disconnect(connection_id: str) -> Dict:
    """Handle WebSocket disconnection"""
    try:
        # Get session before removing it
        session = session_manager.get_session(connection_id)

        # Remove the session
        session_manager.remove_session(connection_id)

        # If user was in a game, handle cleanup
        if session and session.get('game_id'):
            game_id = session['game_id']
            player_number = session.get('player_number')
            print(f"Player {player_number} disconnected from game {game_id}")

            # Get the game to check its status
            try:
                game_response = games_table.get_item(Key={'game_id': game_id})

                if 'Item' in game_response:
                    game = game_response['Item']
                    game_status = game.get('game_status')

                    # Only process if game is still active
                    if game_status not in ['completed', 'tombstoned']:
                        print(f"Game {game_id} is still active, removing player {player_number}")

                        # Remove player from game state
                        from blackjack_models import BlackjackGameState
                        game_state = BlackjackGameState.from_dict(game['game_state'])

                        # Check if it was this player's turn
                        was_players_turn = (game_state.current_player_turn == player_number)

                        game_state.remove_player(player_number)

                        # If it was their turn during playing phase, advance to next player
                        if was_players_turn and game_state.phase == 'playing':
                            game_state.current_player_turn = game_state._get_next_player_turn(None)
                            # If no more players, trigger dealer turn
                            if game_state.current_player_turn is None:
                                game_state.phase = 'dealer_turn'
                                game_state.dealer_play()

                        # Update game in database
                        games_table.update_item(
                            Key={'game_id': game_id},
                            UpdateExpression='SET game_state = :state',
                            ExpressionAttributeValues={
                                ':state': game_state.to_dict(include_deck=True)
                            }
                        )

                        # Notify other players that this player disconnected
                        game_sessions = session_manager.get_sessions_by_game(game_id)
                        if game_sessions and ws_utils:
                            for other_session in game_sessions:
                                if other_session.get('connection_id') != connection_id:
                                    ws_utils.send_message(other_session['connection_id'], {
                                        'type': 'player_disconnected',
                                        'message': f'Player {player_number} disconnected',
                                        'player_number': player_number,
                                        'game_state': game_state.to_dict()
                                    })

            except Exception as e:
                print(f"Error handling game on disconnect: {str(e)}")

        print(f"WebSocket connection closed: {connection_id}")
        return {'statusCode': 200}
    except Exception as e:
        print(f"Disconnect error: {str(e)}")
        return {'statusCode': 200}


def handle_default_message(event: Dict, connection_id: str) -> Dict:
    """Handle messages sent to $default route"""
    try:
        print(f"Default route - Connection ID: {connection_id}")

        body_str = event.get('body', '{}')
        body = json.loads(body_str)
        action = body.get('action')

        print(f"Default route - Action: {action}")

        if not action:
            return send_error(connection_id, "Missing 'action' in message")

        # Route based on action
        if action == 'create_game':
            return ws_create_game(body, connection_id)
        elif action == 'join_game':
            return ws_join_game(body, connection_id)
        elif action == 'start_round':
            return ws_start_round(body, connection_id)
        elif action == 'place_bet':
            return ws_place_bet(body, connection_id)
        elif action == 'hit':
            return ws_hit(body, connection_id)
        elif action == 'stand':
            return ws_stand(body, connection_id)
        elif action == 'double_down':
            return ws_double_down(body, connection_id)
        elif action == 'split':
            return ws_split(body, connection_id)
        elif action == 'get_game':
            return ws_get_game(body, connection_id)
        elif action == 'get_balance':
            return ws_get_balance(body, connection_id)
        elif action == 'reconnect':
            return ws_reconnect(body, connection_id)
        elif action == 'leave_game':
            return ws_leave_game(body, connection_id)
        elif action == 'send_chat':
            return ws_send_chat(body, connection_id)
        elif action == 'claim_ad_reward':
            return ws_claim_ad_reward(body, connection_id)
        else:
            return send_error(connection_id, f"Unknown action: {action}")

    except json.JSONDecodeError as e:
        print(f"JSON decode error: {str(e)}")
        return send_error(connection_id, "Invalid JSON message")
    except Exception as e:
        print(f"Default message handler error: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return send_error(connection_id, f"Internal server error: {str(e)}")


def ws_create_game(body: Dict, connection_id: str) -> Dict:
    """WebSocket create game handler"""
    try:
        user_id = body.get('user_id')
        apn_token = body.get('apn_token')
        visibility = body.get('visibility', 'private')
        initial_balance = body.get('initial_balance', 1000)

        if not user_id or not apn_token:
            return send_error(connection_id, "user_id and apn_token are required")

        result = game_service.create_game(connection_id, user_id, apn_token, visibility, initial_balance)

        return ws_utils.send_message(connection_id, {
            'type': 'game_created',
            'data': result
        })

    except Exception as e:
        print(f"ws_create_game error: {str(e)}")
        return send_error(connection_id, f"Create game failed: {str(e)}")


def ws_join_game(body: Dict, connection_id: str) -> Dict:
    """WebSocket join game handler"""
    try:
        game_id = body.get('game_id')
        user_id = body.get('user_id')
        apn_token = body.get('apn_token')

        if not all([game_id, user_id, apn_token]):
            return send_error(connection_id, "game_id, user_id, and apn_token are required")

        result = game_service.join_game(connection_id, game_id, user_id, apn_token)

        return ws_utils.send_message(connection_id, {
            'type': 'game_joined',
            'data': result
        })

    except Exception as e:
        print(f"Join game error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_start_round(body: Dict, connection_id: str) -> Dict:
    """WebSocket start round handler"""
    try:
        game_id = body.get('game_id')

        if not game_id:
            return send_error(connection_id, "game_id is required")

        result = game_service.start_round(connection_id, game_id)

        return ws_utils.send_message(connection_id, {
            'type': 'round_started',
            'data': result
        })

    except Exception as e:
        print(f"Start round error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_place_bet(body: Dict, connection_id: str) -> Dict:
    """WebSocket place bet handler"""
    try:
        game_id = body.get('game_id')
        bet_amount = body.get('bet_amount')

        if not game_id or bet_amount is None:
            return send_error(connection_id, "game_id and bet_amount are required")

        result = game_service.place_bet(connection_id, game_id, bet_amount)

        return ws_utils.send_message(connection_id, {
            'type': 'bet_placed',
            'data': result
        })

    except Exception as e:
        print(f"Place bet error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_hit(body: Dict, connection_id: str) -> Dict:
    """WebSocket hit handler"""
    try:
        game_id = body.get('game_id')

        if not game_id:
            return send_error(connection_id, "game_id is required")

        result = game_service.hit(connection_id, game_id)

        return ws_utils.send_message(connection_id, {
            'type': 'card_dealt',
            'data': result
        })

    except Exception as e:
        print(f"Hit error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_stand(body: Dict, connection_id: str) -> Dict:
    """WebSocket stand handler"""
    try:
        game_id = body.get('game_id')

        if not game_id:
            return send_error(connection_id, "game_id is required")

        result = game_service.stand(connection_id, game_id)

        return ws_utils.send_message(connection_id, {
            'type': 'stand_complete',
            'data': result
        })

    except Exception as e:
        print(f"Stand error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_double_down(body: Dict, connection_id: str) -> Dict:
    """WebSocket double down handler"""
    try:
        game_id = body.get('game_id')

        if not game_id:
            return send_error(connection_id, "game_id is required")

        result = game_service.double_down(connection_id, game_id)

        return ws_utils.send_message(connection_id, {
            'type': 'double_down_complete',
            'data': result
        })

    except Exception as e:
        print(f"Double down error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_split(body: Dict, connection_id: str) -> Dict:
    """WebSocket split handler"""
    try:
        game_id = body.get('game_id')

        if not game_id:
            return send_error(connection_id, "game_id is required")

        result = game_service.split(connection_id, game_id)

        return ws_utils.send_message(connection_id, {
            'type': 'split_complete',
            'data': result
        })

    except Exception as e:
        print(f"Split error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_get_game(body: Dict, connection_id: str) -> Dict:
    """WebSocket get game handler"""
    try:
        game_id = body.get('game_id')

        if not game_id:
            return send_error(connection_id, "game_id is required")

        game = game_service.get_game(game_id)
        return ws_utils.send_message(connection_id, {
            'type': 'game_state',
            'data': game
        })

    except Exception as e:
        print(f"Get game error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_get_balance(body: Dict, connection_id: str) -> Dict:
    """WebSocket get user balance handler"""
    try:
        user_id = body.get('user_id')

        if not user_id:
            return send_error(connection_id, "user_id is required")

        balance_info = game_service.get_user_balance(user_id)
        return ws_utils.send_message(connection_id, {
            'type': 'user_balance',
            'data': balance_info
        })

    except Exception as e:
        print(f"Get balance error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_reconnect(body: Dict, connection_id: str) -> Dict:
    """WebSocket reconnect handler"""
    try:
        game_id = body.get('game_id')
        user_id = body.get('user_id')

        if not game_id or not user_id:
            return send_error(connection_id, "game_id and user_id are required for reconnection")

        # Get the game
        response = games_table.get_item(Key={'game_id': game_id})

        if 'Item' not in response:
            return send_error(connection_id, 'Game not found')

        game = response['Item']
        game_status = game.get('game_status')

        if game_status in ['tombstoned']:
            return send_error(connection_id, 'Game has ended and cannot be resumed')

        # Verify this user is the player
        if game.get('player_user_id') != user_id:
            return send_error(connection_id, 'You are not the player in this game')

        apn_token = game.get('player_apn')

        # Update session with the new connection ID
        session_manager.join_game(connection_id, game_id, user_id, apn_token, 1)

        print(f"Player reconnected to game {game_id}")

        result = {
            'game_id': game_id,
            'message': 'Successfully reconnected to the game',
            'game_status': game_status,
            'player_number': 1,
            'game_state': decimal_to_int(game.get('game_state')),
            'initial_balance': game.get('initial_balance', 1000)
        }

        return ws_utils.send_message(connection_id, {
            'type': 'reconnected',
            'data': result
        })

    except Exception as e:
        print(f"Reconnect error: {str(e)}")
        return send_error(connection_id, f"Reconnect failed: {str(e)}")


def ws_leave_game(body: Dict, connection_id: str) -> Dict:
    """WebSocket leave game handler"""
    try:
        game_id = body.get('game_id')

        if not game_id:
            return send_error(connection_id, "game_id is required")

        # Get session
        session = session_manager.get_session(connection_id)
        if not session:
            return send_error(connection_id, 'Session not found')

        if session.get('game_id') != game_id:
            return send_error(connection_id, 'You are not in this game')

        user_id = session.get('user_id')
        player_number = session.get('player_number')

        # Get the game
        game_response = games_table.get_item(Key={'game_id': game_id})
        if 'Item' not in game_response:
            return send_error(connection_id, 'Game not found')

        game = game_response['Item']

        # Remove player from game state
        from blackjack_models import BlackjackGameState
        game_state = BlackjackGameState.from_dict(game['game_state'])

        # Check if it was this player's turn
        was_players_turn = (game_state.current_player_turn == player_number)

        game_state.remove_player(player_number)

        # If it was their turn during playing phase, advance to next player
        if was_players_turn and game_state.phase == 'playing':
            game_state.current_player_turn = game_state._get_next_player_turn(None)
            # If no more players, trigger dealer turn
            if game_state.current_player_turn is None:
                game_state.phase = 'dealer_turn'
                game_state.dealer_play()

        # Update game in database
        games_table.update_item(
            Key={'game_id': game_id},
            UpdateExpression='SET game_state = :state',
            ExpressionAttributeValues={
                ':state': game_state.to_dict(include_deck=True)
            }
        )

        # Notify other players
        game_sessions = session_manager.get_sessions_by_game(game_id)
        if game_sessions and ws_utils:
            for other_session in game_sessions:
                if other_session.get('connection_id') != connection_id:
                    ws_utils.send_message(other_session['connection_id'], {
                        'type': 'player_left',
                        'message': f'Player {player_number} left the game',
                        'player_number': player_number,
                        'game_state': game_state.to_dict()
                    })

        # Remove the session
        session_manager.remove_session(connection_id)

        return ws_utils.send_message(connection_id, {
            'type': 'left_game',
            'message': 'Successfully left the game',
            'game_id': game_id
        })

    except Exception as e:
        print(f"Leave game error: {str(e)}")
        return send_error(connection_id, f"Leave game failed: {str(e)}")


def ws_send_chat(body: Dict, connection_id: str) -> Dict:
    """WebSocket send chat message handler"""
    try:
        game_id = body.get('game_id')
        message = body.get('message')

        if not game_id:
            return send_error(connection_id, "game_id is required")
        if not message:
            return send_error(connection_id, "message is required")

        result = game_service.send_chat(connection_id, game_id, message)

        return ws_utils.send_message(connection_id, {
            'type': 'chat_sent',
            'data': result
        })

    except Exception as e:
        print(f"Send chat error: {str(e)}")
        return send_error(connection_id, str(e))


def ws_claim_ad_reward(body: Dict, connection_id: str) -> Dict:
    """WebSocket claim ad reward handler"""
    try:
        user_id = body.get('user_id')
        ad_network = body.get('ad_network')
        ad_unit_id = body.get('ad_unit_id')

        if not user_id:
            return send_error(connection_id, "user_id is required")

        result = game_service.claim_ad_reward(user_id, ad_network, ad_unit_id)

        return ws_utils.send_message(connection_id, {
            'type': 'ad_reward_claimed',
            'data': result
        })

    except Exception as e:
        print(f"Claim ad reward error: {str(e)}")
        return send_error(connection_id, str(e))


def send_error(connection_id: str, error_message: str) -> Dict:
    """Send an error message to a WebSocket connection"""
    return ws_utils.send_error(connection_id, error_message)


def decimal_to_int(obj):
    """Convert DynamoDB Decimal types to int for JSON serialization"""
    if isinstance(obj, list):
        return [decimal_to_int(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: decimal_to_int(value) for key, value in obj.items()}
    elif isinstance(obj, Decimal):
        return int(obj)
    return obj