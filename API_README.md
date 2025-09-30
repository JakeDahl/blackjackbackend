# Blackjack WebSocket API Documentation

## Overview

This is a real-time **multiplayer** blackjack game backend built with AWS Lambda, API Gateway WebSocket, and DynamoDB. The API supports up to **5 players** at a single table, where players compete against the dealer following standard blackjack rules.

## WebSocket Connection

**Endpoint Format:** `wss://{api-id}.execute-api.{region}.amazonaws.com/prod`

The WebSocket API uses a message-based protocol where clients send JSON messages with an `action` field to specify the operation.

## Authentication

Currently, the API uses `user_id` and `apn_token` for basic player identification. These should be included in game creation and join operations.

## Message Format

### Client → Server

All messages follow this format:

```json
{
  "action": "action_name",
  "param1": "value1",
  "param2": "value2"
}
```

### Server → Client

All responses follow this format:

```json
{
  "type": "response_type",
  "data": {
    // Response data
  },
  "message": "Human-readable message (optional)"
}
```

## Multiplayer Game Flow

1. **Connect** → WebSocket connection established
2. **Create Game** → Player 1 creates a game table (waiting for players)
3. **Join Game** → Players 2-5 join using game_id
4. **Start Round** → Any player initiates betting phase
5. **Place Bets** → All players place their bets
6. **Play Hands** → Players take turns (hit, stand, double down)
7. **Dealer Plays** → Dealer plays after all players finish
8. **Round Over** → Results distributed, balances updated
9. **Repeat** → Start new round or players leave

## API Actions

### 1. Create Game

Create a new multiplayer blackjack table.

**Request:**
```json
{
  "action": "create_game",
  "user_id": "unique_user_identifier",
  "apn_token": "apple_push_notification_token",
  "visibility": "private",
  "initial_balance": 1000
}
```

**Parameters:**
- `user_id` (string, required): Unique identifier for the player
- `apn_token` (string, required): Apple Push Notification token for the player
- `visibility` (string, optional): Game visibility - "private" or "public" (default: "private")
- `initial_balance` (integer, optional): Starting chip balance for all players (default: 1000)

**Response:**
```json
{
  "type": "game_created",
  "data": {
    "game_id": "A1B2",
    "message": "Game created successfully. Waiting for players (1/5).",
    "game_status": "waiting_for_players",
    "player_number": 1,
    "game_state": {
      "dealer_hand": [],
      "players": {
        "1": {
          "player_number": 1,
          "user_id": "user123",
          "balance": 1000,
          "hand": [],
          "current_bet": 0,
          "has_bet": false
        }
      },
      "phase": "waiting",
      "current_player_turn": null,
      "round_active": false
    },
    "initial_balance": 1000
  }
}
```

---

### 2. Join Game

Join an existing multiplayer game.

**Request:**
```json
{
  "action": "join_game",
  "game_id": "A1B2",
  "user_id": "unique_user_identifier",
  "apn_token": "apple_push_notification_token"
}
```

**Parameters:**
- `game_id` (string, required): Game identifier from create_game
- `user_id` (string, required): Unique identifier for the player
- `apn_token` (string, required): Apple Push Notification token

**Response:**
```json
{
  "type": "game_joined",
  "data": {
    "game_id": "A1B2",
    "message": "Successfully joined the game as Player 2",
    "game_status": "active",
    "player_number": 2,
    "game_state": {
      "dealer_hand": [],
      "players": {
        "1": { /* Player 1 state */ },
        "2": { /* Player 2 state */ }
      },
      "phase": "waiting",
      "current_player_turn": null
    },
    "initial_balance": 1000
  }
}
```

**Other Players Notified:**
```json
{
  "type": "player_joined",
  "message": "Player 2 joined the game",
  "player_number": 2,
  "total_players": 2,
  "game_state": { /* Updated game state */ }
}
```

---

### 3. Start Round

Initiate a new round of betting. Any player can start a round.

**Request:**
```json
{
  "action": "start_round",
  "game_id": "A1B2"
}
```

**Parameters:**
- `game_id` (string, required): Game identifier

**Response:**
```json
{
  "type": "round_started",
  "data": {
    "game_id": "A1B2",
    "message": "Betting phase started. All players place your bets.",
    "game_state": {
      "phase": "betting",
      "round_active": true,
      "players": {
        "1": { "has_bet": false, "hand": [], "current_bet": 0 },
        "2": { "has_bet": false, "hand": [], "current_bet": 0 }
      }
    }
  }
}
```

**All Players Notified:**
```json
{
  "type": "betting_started",
  "message": "Place your bets",
  "game_state": { /* Current game state */ }
}
```

---

### 4. Place Bet

Place a bet for the current round.

**Request:**
```json
{
  "action": "place_bet",
  "game_id": "A1B2",
  "bet_amount": 50
}
```

**Parameters:**
- `game_id` (string, required): Game identifier
- `bet_amount` (integer, required): Amount to bet (must be ≤ player balance)

**Response:**
```json
{
  "type": "bet_placed",
  "data": {
    "game_id": "A1B2",
    "message": "Bet placed",
    "game_state": {
      "phase": "betting",  // or "playing" if all bets placed
      "players": {
        "1": {
          "balance": 950,
          "current_bet": 50,
          "has_bet": true
        }
      }
    },
    "bet_amount": 50
  }
}
```

**When All Bets Placed:**
Cards are automatically dealt and phase changes to `"playing"` with `current_player_turn` set to first player.

**Other Players Notified:**
```json
{
  "type": "player_bet_placed",
  "player_number": 1,
  "message": "Player 1 placed bet",
  "game_state": { /* Updated game state */ }
}
```

---

### 5. Hit

Take another card during your turn.

**Request:**
```json
{
  "action": "hit",
  "game_id": "A1B2"
}
```

**Parameters:**
- `game_id` (string, required): Game identifier

**Response:**
```json
{
  "type": "card_dealt",
  "data": {
    "game_id": "A1B2",
    "message": "Card dealt",
    "game_state": {
      "phase": "playing",
      "current_player_turn": 1,  // or next player, or null if dealer's turn
      "players": {
        "1": {
          "hand": [
            {"rank": "K", "suit": "hearts"},
            {"rank": "7", "suit": "diamonds"},
            {"rank": "3", "suit": "clubs"}
          ],
          "busted": false,
          "can_double_down": false
        }
      }
    }
  }
}
```

**Other Players Notified:**
```json
{
  "type": "player_hit",
  "player_number": 1,
  "message": "Player 1 hit",
  "game_state": { /* Updated game state */ }
}
```

**Turn Management:**
- Only the player whose turn it is (`current_player_turn`) can act
- After acting, turn automatically passes to next player
- When all players have acted, dealer plays automatically

---

### 6. Stand

End your turn with current hand.

**Request:**
```json
{
  "action": "stand",
  "game_id": "A1B2"
}
```

**Parameters:**
- `game_id` (string, required): Game identifier

**Response:**
```json
{
  "type": "stand_complete",
  "data": {
    "game_id": "A1B2",
    "message": "Player stood",
    "game_state": {
      "phase": "playing",  // or "round_over" if all done
      "current_player_turn": 2,  // next player
      "players": {
        "1": {
          "stood": true,
          "has_acted": true
        }
      }
    }
  }
}
```

**Other Players Notified:**
```json
{
  "type": "player_stood",
  "player_number": 1,
  "message": "Player 1 stood",
  "game_state": { /* Updated game state */ }
}
```

---

### 7. Double Down

Double your bet, take one card, end turn.

**Request:**
```json
{
  "action": "double_down",
  "game_id": "A1B2"
}
```

**Parameters:**
- `game_id` (string, required): Game identifier

**Response:**
```json
{
  "type": "double_down_complete",
  "data": {
    "game_id": "A1B2",
    "message": "Doubled down",
    "game_state": {
      "players": {
        "1": {
          "current_bet": 100,
          "balance": 900,
          "hand": [ /* 3 cards */ ],
          "stood": true,
          "has_acted": true
        }
      }
    }
  }
}
```

**Other Players Notified:**
```json
{
  "type": "player_doubled_down",
  "player_number": 1,
  "message": "Player 1 doubled down",
  "game_state": { /* Updated game state */ }
}
```

---

### 8. Split

Split a pair into two separate hands.

**Request:**
```json
{
  "action": "split",
  "game_id": "A1B2"
}
```

**Parameters:**
- `game_id` (string, required): Game identifier

**Response:**
```json
{
  "type": "split_complete",
  "data": {
    "game_id": "A1B2",
    "message": "Hand split",
    "game_state": {
      "players": {
        "1": {
          "hand": [
            {"rank": "8", "suit": "hearts"},
            {"rank": "3", "suit": "clubs"}
          ],
          "split_hand": [
            {"rank": "8", "suit": "diamonds"},
            {"rank": "Q", "suit": "spades"}
          ],
          "current_bet": 50,
          "split_bet": 50,
          "balance": 900,
          "has_split": true,
          "playing_split_hand": false,
          "can_double_down": true
        }
      }
    }
  }
}
```

**Split Rules:**
- Can only split when you have two cards of the same rank (e.g., two 8s, two Queens)
- Requires sufficient balance to match your original bet
- Creates two separate hands, each with one of the original cards
- Each hand receives one additional card immediately
- You play the first hand to completion, then the split hand
- If first hand busts, you still play the split hand
- You can hit, stand, or double down on each hand independently
- Only one split allowed per round (no re-splitting)
- Blackjack after split counts as 21, not blackjack (pays 2:1 instead of 3:2)

**Playing Split Hands:**
After splitting, you play hands in sequence:
1. Play first hand (hit/stand/double)
2. Once first hand is complete, automatically switch to split hand
3. Play split hand (hit/stand/double)
4. After both hands complete, dealer plays and both hands are resolved

**Other Players Notified:**
```json
{
  "type": "player_split",
  "player_number": 1,
  "message": "Player 1 split their hand",
  "game_state": { /* Updated game state */ }
}
```

---

### 9. Get Game State

Retrieve current game state.

**Request:**
```json
{
  "action": "get_game",
  "game_id": "A1B2"
}
```

**Parameters:**
- `game_id` (string, required): Game identifier

**Response:**
```json
{
  "type": "game_state",
  "data": {
    "game_id": "A1B2",
    "game_state": { /* Full game state */ },
    "game_status": "active",
    "visibility": "private",
    "initial_balance": 1000,
    "max_players": 5,
    "created_at": 1234567890,
    "ttl": 1234654290
  }
}
```

---

### 10. Reconnect

Reconnect to an existing game after disconnection.

**Request:**
```json
{
  "action": "reconnect",
  "game_id": "A1B2",
  "user_id": "unique_user_identifier"
}
```

**Parameters:**
- `game_id` (string, required): Game identifier
- `user_id` (string, required): User identifier (must match a player in game)

**Response:**
```json
{
  "type": "reconnected",
  "data": {
    "game_id": "A1B2",
    "message": "Successfully reconnected to the game",
    "game_status": "active",
    "player_number": 2,
    "game_state": { /* Current game state */ },
    "initial_balance": 1000
  }
}
```

---

### 11. Leave Game

Leave the current game.

**Request:**
```json
{
  "action": "leave_game",
  "game_id": "A1B2"
}
```

**Parameters:**
- `game_id` (string, required): Game identifier

**Response:**
```json
{
  "type": "left_game",
  "message": "Successfully left the game",
  "game_id": "A1B2"
}
```

**Note:** If game is active and player leaves mid-round, the game is tombstoned.

---

## Game State Object

The `game_state` object contains all information about the current game:

```json
{
  "deck": [
    // Array of remaining cards (hidden from client in production)
  ],
  "dealer_hand": [
    {"rank": "A", "suit": "clubs"},
    {"rank": "5", "suit": "spades"}
  ],
  "players": {
    "1": {
      "player_number": 1,
      "user_id": "user123",
      "balance": 950,
      "hand": [
        {"rank": "K", "suit": "hearts"},
        {"rank": "7", "suit": "diamonds"}
      ],
      "current_bet": 50,
      "has_bet": true,
      "has_acted": false,
      "stood": false,
      "busted": false,
      "result": null,
      "can_double_down": true,
      "can_split": false
    },
    "2": { /* Player 2 state */ }
  },
  "phase": "playing",
  "current_player_turn": 1,
  "round_active": true
}
```

### Player State Fields

- `player_number`: Seat number (1-5)
- `user_id`: Player's unique identifier
- `balance`: Current chip balance
- `hand`: Array of cards in player's hand
- `current_bet`: Amount bet this round
- `has_bet`: Boolean indicating if player has placed bet
- `has_acted`: Boolean indicating if player has completed their turn
- `stood`: Boolean indicating if player stood
- `busted`: Boolean indicating if player busted (over 21)
- `result`: Round result ('win', 'lose', 'push', 'blackjack', or null)
- `split_hand`: Array of cards in split hand (null if not split)
- `split_bet`: Amount bet on split hand
- `split_stood`: Boolean indicating if split hand has stood
- `split_busted`: Boolean indicating if split hand is busted
- `split_result`: Round result for split hand ('win', 'lose', 'push', or null)
- `can_double_down`: Boolean indicating if double down is available
- `can_split`: Boolean indicating if split is available
- `has_split`: Boolean indicating if player has already split
- `playing_split_hand`: Boolean indicating if currently playing split hand

### Game Phases

- `"waiting"`: Waiting for players to join or round to start
- `"betting"`: Players placing bets
- `"playing"`: Players taking turns (hit, stand, double down)
- `"dealer_turn"`: Dealer is playing (brief, automatic)
- `"round_over"`: Round completed, results available

### Turn Management

- `current_player_turn`: Player number whose turn it is (null when not relevant)
- Players act in order: Player 1, Player 2, Player 3, etc.
- Only the current player can hit, stand, or double down
- Turn automatically advances after each action

### Round Results (per player)

- `"win"`: Player wins the round (pays 2:1)
- `"lose"`: Player loses the round
- `"push"`: Tie, bet returned
- `"blackjack"`: Player got blackjack (pays 3:2)
- `null`: Round not yet completed

### Card Object

```json
{
  "rank": "K",
  "suit": "hearts"
}
```

**Ranks:** `"A"`, `"2"`, `"3"`, `"4"`, `"5"`, `"6"`, `"7"`, `"8"`, `"9"`, `"10"`, `"J"`, `"Q"`, `"K"`

**Suits:** `"hearts"`, `"diamonds"`, `"clubs"`, `"spades"`

**Card Values:**
- Number cards (2-10): Face value
- Face cards (J, Q, K): 10
- Ace: 11 or 1 (automatically adjusted to prevent bust)

---

## Error Messages

Errors are sent with type `"error"`:

```json
{
  "type": "error",
  "message": "Error description",
  "timestamp": 1234567890
}
```

### Common Errors

- `"Missing 'action' in message"` - No action specified
- `"Unknown action: {action}"` - Invalid action name
- `"user_id and apn_token are required"` - Missing required parameters
- `"Game not found"` - Invalid game_id
- `"Game is full"` - Cannot join, 5 players already seated
- `"You are not in this game"` - User not associated with game
- `"Not your turn"` - Trying to act when it's another player's turn
- `"Cannot hit in current phase"` - Action not allowed in current phase
- `"Not in betting phase"` - Trying to bet outside betting phase
- `"Invalid bet amount"` - Bet amount invalid (≤ 0 or > balance)
- `"Cannot double down"` - Double down not available
- `"Cannot split this hand"` - Cards don't match or already split
- `"Insufficient balance to split"` - Not enough balance to match bet

---

## Blackjack Rules

### Hand Values
- Cards 2-10: Face value
- Jack, Queen, King: 10
- Ace: 11 or 1 (automatically uses best value)

### Winning
- Get closer to 21 than dealer without going over
- Blackjack (21 with 2 cards) pays 3:2
- Regular win pays 2:1
- Tie (push) returns bet

### Dealer Rules
- Dealer must hit on 16 or less
- Dealer must stand on 17 or more

### Player Options
- **Hit**: Take another card
- **Stand**: End turn, next player goes (or dealer plays if last player)
- **Double Down**: Double bet, take one card, end turn (only as first action)
- **Split**: Split matching pair into two hands, play each independently (only as first action)

### Multiplayer Specifics
- Up to 5 players at one table
- All players bet before cards are dealt
- Players act in turn order (Player 1 → Player 2 → ... → Player 5)
- Dealer plays after all players complete their hands
- Each player's result is independent (multiple players can win against dealer)

---

## Connection Lifecycle

### 1. Connect
```
Client connects to WebSocket endpoint
→ Server responds with 200 OK
→ Session created in sessions table
```

### 2. Active Session
```
Client sends actions
→ Server processes and responds
→ Game state updated in DynamoDB
→ Other players notified of changes
```

### 3. Disconnect
```
Client disconnects (intentional or network issue)
→ Server cleans up session
→ Game remains in DynamoDB
→ Player can reconnect to resume
```

### 4. Reconnect
```
Client reconnects to WebSocket
→ Client sends reconnect action with game_id and user_id
→ Server restores session and identifies player
→ Client receives current game state
→ Player can continue playing
```

---

## Multiplayer Game Flow Example

### Complete Multiplayer Round

```javascript
// Player 1: Connect and create game
ws1 = new WebSocket('wss://example.execute-api.us-east-1.amazonaws.com/prod');

ws1.send(JSON.stringify({
  action: 'create_game',
  user_id: 'player1',
  apn_token: 'token1',
  initial_balance: 1000
}));
// Response: game_created, game_id: "ABCD", player_number: 1

// Player 2: Connect and join game
ws2 = new WebSocket('wss://example.execute-api.us-east-1.amazonaws.com/prod');

ws2.send(JSON.stringify({
  action: 'join_game',
  game_id: 'ABCD',
  user_id: 'player2',
  apn_token: 'token2'
}));
// Response: game_joined, player_number: 2
// Player 1 receives: player_joined notification

// Player 3: Connect and join
ws3 = new WebSocket('wss://example.execute-api.us-east-1.amazonaws.com/prod');

ws3.send(JSON.stringify({
  action: 'join_game',
  game_id: 'ABCD',
  user_id: 'player3',
  apn_token: 'token3'
}));
// All players notified

// Any player can start round
ws1.send(JSON.stringify({
  action: 'start_round',
  game_id: 'ABCD'
}));
// All players receive: betting_started

// All players place bets
ws1.send(JSON.stringify({
  action: 'place_bet',
  game_id: 'ABCD',
  bet_amount: 50
}));

ws2.send(JSON.stringify({
  action: 'place_bet',
  game_id: 'ABCD',
  bet_amount: 100
}));

ws3.send(JSON.stringify({
  action: 'place_bet',
  game_id: 'ABCD',
  bet_amount: 75
}));
// After last bet, cards auto-dealt, phase becomes "playing"
// current_player_turn: 1

// Player 1's turn
ws1.send(JSON.stringify({
  action: 'hit',
  game_id: 'ABCD'
}));
// All players notified

ws1.send(JSON.stringify({
  action: 'stand',
  game_id: 'ABCD'
}));
// Turn passes to Player 2
// All players notified

// Player 2's turn
ws2.send(JSON.stringify({
  action: 'double_down',
  game_id: 'ABCD'
}));
// Turn passes to Player 3
// All players notified

// Player 3's turn
ws3.send(JSON.stringify({
  action: 'stand',
  game_id: 'ABCD'
}));
// Dealer plays automatically
// All players receive round_over with results
```

---

## Real-time Notifications

All players in a game receive real-time notifications for:

| Event | Notification Type | Triggered By |
|-------|------------------|--------------|
| Player joins | `player_joined` | join_game |
| Round starts | `betting_started` | start_round |
| Player bets | `player_bet_placed` | place_bet |
| Player hits | `player_hit` | hit |
| Player stands | `player_stood` | stand |
| Player doubles | `player_doubled_down` | double_down |
| Player splits | `player_split` | split |
| Dealer plays | Included in phase change | Automatic |

---

## Best Practices for App Development

### 1. Connection Management
- Implement automatic reconnection on disconnect
- Store game_id, user_id, and player_number locally
- Show connection status to user
- Handle reconnect flow gracefully

### 2. UI Updates
- Update UI immediately when receiving notifications
- Show all players' hands and bets
- Highlight current player's turn
- Display player numbers/names clearly
- Show waiting states during other players' turns

### 3. Turn Management
- Disable actions when not player's turn
- Show visual indicator of whose turn it is
- Display timer/countdown for turn limits (if implemented)
- Queue actions if player tries to act out of turn

### 4. Multiplayer UX
```javascript
function renderGameTable(gameState) {
  // Show all players around table
  for (let [playerNum, player] of Object.entries(gameState.players)) {
    renderPlayerSeat(playerNum, player, {
      isCurrentTurn: gameState.current_player_turn == playerNum,
      isMe: playerNum == myPlayerNumber
    });
  }

  // Show dealer
  renderDealer(gameState.dealer_hand, gameState.phase);

  // Enable/disable actions
  if (gameState.current_player_turn == myPlayerNumber) {
    enableActions(gameState.players[myPlayerNumber]);
  } else {
    disableActions();
  }
}
```

### 5. Betting Phase
- Show countdown when all players need to bet
- Display who has/hasn't bet yet
- Auto-advance to playing phase when all bets placed

### 6. Game Phase Handling
```javascript
switch (gameState.phase) {
  case 'waiting':
    // Show "Waiting for players" or "Start Round" button
    break;
  case 'betting':
    // Show bet input if haven't bet
    // Show waiting if already bet
    break;
  case 'playing':
    // Show action buttons if your turn
    // Show waiting if not your turn
    break;
  case 'round_over':
    // Show results for all players
    // Show "Start New Round" button
    break;
}
```

---

## Testing

### Test Multiplayer Flow
1. Open 3+ WebSocket connections
2. Create game on first connection
3. Join game on other connections
4. Start round
5. Place bets on all connections
6. Verify cards dealt automatically
7. Take turns in sequence
8. Verify dealer plays after all players act
9. Verify results distributed correctly

### Edge Cases to Test
- Player disconnects mid-round
- Player reconnects during their turn
- All players bust
- Multiple players get blackjack
- One player in game (single player mode still works)
- Game at max capacity (6th player tries to join)
- Player tries to act out of turn

---

## Deployment Information

The backend is deployed on AWS with:
- **Lambda**: Python 3.11 on ARM64
- **DynamoDB Tables**:
  - `blackjack-games`: Game state storage (up to 5 players per game)
  - `blackjack-websocket-sessions`: Connection management
- **API Gateway**: WebSocket API
- **Deck**: 6-deck shoe (312 cards) for multiplayer games
- **Region**: Configurable via CDK deployment

---

## Quick Reference

| Action | Required Params | Response Type | Players Notified |
|--------|----------------|---------------|------------------|
| `create_game` | `user_id`, `apn_token` | `game_created` | No |
| `join_game` | `game_id`, `user_id`, `apn_token` | `game_joined` | Yes - `player_joined` |
| `start_round` | `game_id` | `round_started` | Yes - `betting_started` |
| `place_bet` | `game_id`, `bet_amount` | `bet_placed` | Yes - `player_bet_placed` |
| `hit` | `game_id` | `card_dealt` | Yes - `player_hit` |
| `stand` | `game_id` | `stand_complete` | Yes - `player_stood` |
| `double_down` | `game_id` | `double_down_complete` | Yes - `player_doubled_down` |
| `split` | `game_id` | `split_complete` | Yes - `player_split` |
| `get_game` | `game_id` | `game_state` | No |
| `reconnect` | `game_id`, `user_id` | `reconnected` | No |
| `leave_game` | `game_id` | `left_game` | No |

---

## Future Enhancements

Potential features not yet implemented:
- Insurance when dealer shows Ace
- Re-splitting (splitting already split hands)
- Side bets
- Spectator mode
- Chat between players
- Player profiles and stats
- Achievements/badges
- Tournament mode
- Configurable table rules
- Tipping/gifting between players