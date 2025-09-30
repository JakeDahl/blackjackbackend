"""
Blackjack game models and logic
"""
import random
from typing import List, Dict, Optional
from enum import Enum


class Suit(Enum):
    HEARTS = "hearts"
    DIAMONDS = "diamonds"
    CLUBS = "clubs"
    SPADES = "spades"


class Card:
    """Represents a playing card"""
    def __init__(self, rank: str, suit: Suit):
        self.rank = rank
        self.suit = suit

    def value(self) -> int:
        """Get card value for blackjack (face cards = 10, Ace = 11 or 1)"""
        if self.rank in ['J', 'Q', 'K']:
            return 10
        elif self.rank == 'A':
            return 11  # Aces are initially valued at 11, adjusted later if needed
        else:
            return int(self.rank)

    def to_dict(self) -> Dict:
        return {
            'rank': self.rank,
            'suit': self.suit.value
        }

    @staticmethod
    def from_dict(data: Dict) -> 'Card':
        return Card(data['rank'], Suit(data['suit']))

    def __repr__(self):
        return f"{self.rank}{self.suit.value[0].upper()}"

    def __eq__(self, other):
        return self.rank == other.rank and self.suit == other.suit


class Deck:
    """Standard 52-card deck"""
    RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']

    def __init__(self):
        self.cards: List[Card] = []
        self.reset()

    def reset(self):
        """Create a fresh deck"""
        self.cards = [Card(rank, suit) for suit in Suit for rank in self.RANKS]

    def shuffle(self):
        """Shuffle the deck"""
        random.shuffle(self.cards)

    def deal(self, num_cards: int) -> List[Card]:
        """Deal cards from the deck"""
        if len(self.cards) < num_cards:
            raise ValueError("Not enough cards in deck")
        dealt = self.cards[:num_cards]
        self.cards = self.cards[num_cards:]
        return dealt


class BlackjackHand:
    """Represents a blackjack hand with scoring logic"""

    def __init__(self, cards: List[Card] = None):
        self.cards = cards or []

    def add_card(self, card: Card):
        """Add a card to the hand"""
        self.cards.append(card)

    def calculate_value(self) -> int:
        """Calculate the best value for the hand"""
        value = 0
        aces = 0

        for card in self.cards:
            if card.rank == 'A':
                aces += 1
                value += 11
            else:
                value += card.value()

        # Adjust for aces if hand is bust
        while value > 21 and aces > 0:
            value -= 10
            aces -= 1

        return value

    def is_bust(self) -> bool:
        """Check if hand is bust (over 21)"""
        return self.calculate_value() > 21

    def is_blackjack(self) -> bool:
        """Check if hand is a natural blackjack (21 with 2 cards)"""
        return len(self.cards) == 2 and self.calculate_value() == 21

    def to_dict(self) -> List[Dict]:
        """Convert hand to dictionary"""
        return [card.to_dict() for card in self.cards]

    @staticmethod
    def from_dict(data: List[Dict]) -> 'BlackjackHand':
        """Create hand from dictionary"""
        cards = [Card.from_dict(c) for c in data]
        return BlackjackHand(cards)


class PlayerState:
    """Represents a single player's state in the game"""

    def __init__(self, player_number: int, user_id: str, balance: int = 1000):
        self.player_number = player_number
        self.user_id = user_id
        self.balance = balance
        self.hand = BlackjackHand()
        self.split_hand: Optional[BlackjackHand] = None  # Second hand after split
        self.current_bet = 0
        self.split_bet = 0  # Bet for split hand
        self.has_bet = False
        self.has_acted = False
        self.stood = False
        self.busted = False
        self.split_stood = False  # Whether split hand has stood
        self.split_busted = False  # Whether split hand is busted
        self.result: Optional[str] = None  # 'win', 'lose', 'push', 'blackjack'
        self.split_result: Optional[str] = None  # Result for split hand
        self.can_double_down = False
        self.can_split = False
        self.has_split = False  # Whether player has already split
        self.playing_split_hand = False  # Currently playing split hand

    def to_dict(self) -> Dict:
        return {
            'player_number': self.player_number,
            'user_id': self.user_id,
            'balance': self.balance,
            'hand': self.hand.to_dict(),
            'split_hand': self.split_hand.to_dict() if self.split_hand else None,
            'current_bet': self.current_bet,
            'split_bet': self.split_bet,
            'has_bet': self.has_bet,
            'has_acted': self.has_acted,
            'stood': self.stood,
            'busted': self.busted,
            'split_stood': self.split_stood,
            'split_busted': self.split_busted,
            'result': self.result,
            'split_result': self.split_result,
            'can_double_down': self.can_double_down,
            'can_split': self.can_split,
            'has_split': self.has_split,
            'playing_split_hand': self.playing_split_hand
        }

    @staticmethod
    def from_dict(data: Dict) -> 'PlayerState':
        player = PlayerState(
            player_number=data['player_number'],
            user_id=data['user_id'],
            balance=data['balance']
        )
        player.hand = BlackjackHand.from_dict(data['hand'])
        player.split_hand = BlackjackHand.from_dict(data['split_hand']) if data.get('split_hand') else None
        player.current_bet = data['current_bet']
        player.split_bet = data.get('split_bet', 0)
        player.has_bet = data.get('has_bet', False)
        player.has_acted = data.get('has_acted', False)
        player.stood = data.get('stood', False)
        player.busted = data.get('busted', False)
        player.split_stood = data.get('split_stood', False)
        player.split_busted = data.get('split_busted', False)
        player.result = data.get('result')
        player.split_result = data.get('split_result')
        player.can_double_down = data.get('can_double_down', False)
        player.can_split = data.get('can_split', False)
        player.has_split = data.get('has_split', False)
        player.playing_split_hand = data.get('playing_split_hand', False)
        return player


class BlackjackGameState:
    """Represents the complete state of a multiplayer blackjack game"""

    MAX_PLAYERS = 5

    def __init__(self):
        # Initialize 6-deck shoe for multiplayer
        self.deck = Deck()
        for _ in range(5):
            temp_deck = Deck()
            self.deck.cards.extend(temp_deck.cards)
        self.deck.shuffle()

        self.dealer_hand = BlackjackHand()
        self.players: Dict[int, PlayerState] = {}  # player_number -> PlayerState
        self.phase = 'waiting'  # waiting, betting, playing, dealer_turn, round_over
        self.current_player_turn: Optional[int] = None  # Which player's turn it is
        self.round_active = False

    def add_player(self, player_number: int, user_id: str, balance: int = 1000) -> bool:
        """Add a player to the game"""
        if len(self.players) >= self.MAX_PLAYERS:
            return False
        if player_number in self.players:
            return False

        self.players[player_number] = PlayerState(player_number, user_id, balance)
        return True

    def remove_player(self, player_number: int) -> bool:
        """Remove a player from the game"""
        if player_number in self.players:
            del self.players[player_number]
            return True
        return False

    def start_betting_phase(self):
        """Start betting phase for a new round"""
        if not self.players:
            return

        # Reset all players for new round
        for player in self.players.values():
            player.hand = BlackjackHand()
            player.split_hand = None
            player.current_bet = 0
            player.split_bet = 0
            player.has_bet = False
            player.has_acted = False
            player.stood = False
            player.busted = False
            player.split_stood = False
            player.split_busted = False
            player.result = None
            player.split_result = None
            player.can_double_down = False
            player.can_split = False
            player.has_split = False
            player.playing_split_hand = False

        self.dealer_hand = BlackjackHand()
        self.phase = 'betting'
        self.current_player_turn = None
        self.round_active = True

        # Check if deck needs reshuffling (less than 52 cards = 1 deck remaining)
        # Reshuffle when running low to ensure enough cards for next round
        if len(self.deck.cards) < 52:
            print(f"Deck running low ({len(self.deck.cards)} cards), reshuffling 6-deck shoe")
            self.deck = Deck()
            for _ in range(5):
                temp_deck = Deck()
                self.deck.cards.extend(temp_deck.cards)
            self.deck.shuffle()

    def place_bet(self, player_number: int, amount: int) -> bool:
        """Player places a bet"""
        if player_number not in self.players:
            return False

        player = self.players[player_number]
        if amount <= 0 or amount > player.balance:
            return False

        player.current_bet = amount
        player.balance -= amount
        player.has_bet = True
        return True

    def all_bets_placed(self) -> bool:
        """Check if all players have placed their bets"""
        return all(p.has_bet for p in self.players.values())

    def start_playing_phase(self):
        """Deal cards and start playing phase"""
        if self.phase != 'betting' or not self.all_bets_placed():
            raise Exception("Cannot start playing phase")

        # Deal two cards to each player who has placed a bet, and dealer
        for _ in range(2):
            for player in sorted(self.players.values(), key=lambda p: p.player_number):
                if player.has_bet:  # Only deal to players who have placed bets
                    player.hand.add_card(self.deck.deal(1)[0])
            self.dealer_hand.add_card(self.deck.deal(1)[0])

        # Check if dealer has blackjack (casino rules - check before player actions)
        if self.dealer_hand.is_blackjack():
            # Dealer has blackjack - resolve all hands immediately
            for player in self.players.values():
                if player.has_bet:
                    if player.hand.is_blackjack():
                        player.result = 'push'
                        player.balance += player.current_bet  # Return bet
                    else:
                        player.result = 'lose'
                    player.has_acted = True
                    player.stood = True

            self.phase = 'round_over'
            self.round_active = False
            return

        # Check for blackjacks and set player options for players who have bet
        for player in self.players.values():
            if player.has_bet:
                player.can_double_down = True
                player.can_split = (player.hand.cards[0].rank == player.hand.cards[1].rank and
                                  player.balance >= player.current_bet)

                if player.hand.is_blackjack():
                    player.has_acted = True
                    player.stood = True
                    # Result determined after dealer plays

        self.phase = 'playing'
        self.current_player_turn = self._get_next_player_turn(None)

    def _get_next_player_turn(self, current_player: Optional[int]) -> Optional[int]:
        """Get the next player who needs to act"""
        player_numbers = sorted(self.players.keys())

        if current_player is None:
            # Start with first player
            start_idx = 0
        else:
            # Find current player and move to next
            try:
                current_idx = player_numbers.index(current_player)
                start_idx = current_idx + 1
            except ValueError:
                start_idx = 0

        # Find next player who hasn't acted
        for i in range(start_idx, len(player_numbers)):
            player_num = player_numbers[i]
            player = self.players[player_num]
            if not player.has_acted and not player.busted and not player.stood:
                return player_num

        return None

    def hit(self, player_number: int):
        """Player takes another card"""
        if self.phase != 'playing':
            raise Exception("Cannot hit in current phase")
        if self.current_player_turn != player_number:
            raise Exception("Not your turn")

        player = self.players[player_number]

        # Check if playing split hand
        if player.has_split and player.playing_split_hand:
            # Use hit_split for split hand
            return self.hit_split(player_number)

        player.hand.add_card(self.deck.deal(1)[0])
        player.can_double_down = False
        player.can_split = False

        # Check if player busts
        if player.hand.is_bust():
            player.busted = True
            player.result = 'lose'

            # If has split hand, switch to it
            if player.has_split:
                player.playing_split_hand = True
            else:
                player.has_acted = True
                self.current_player_turn = self._get_next_player_turn(player_number)
                if self.current_player_turn is None:
                    self.phase = 'dealer_turn'

    def stand(self, player_number: int):
        """Player stands with current hand"""
        if self.phase != 'playing':
            raise Exception("Cannot stand in current phase")
        if self.current_player_turn != player_number:
            raise Exception("Not your turn")

        player = self.players[player_number]

        # Check if playing split hand
        if player.has_split and player.playing_split_hand:
            # Use stand_split for split hand
            return self.stand_split(player_number)

        player.stood = True

        # If has split hand, switch to it
        if player.has_split:
            player.playing_split_hand = True
        else:
            player.has_acted = True
            self.current_player_turn = self._get_next_player_turn(player_number)
            if self.current_player_turn is None:
                self.phase = 'dealer_turn'

    def double_down(self, player_number: int):
        """Player doubles their bet and takes exactly one more card"""
        if self.phase != 'playing':
            raise Exception("Cannot double down in current phase")
        if self.current_player_turn != player_number:
            raise Exception("Not your turn")

        player = self.players[player_number]

        # Check if playing split hand
        if player.has_split and player.playing_split_hand:
            # Double down on split hand
            if not player.can_double_down:
                raise Exception("Cannot double down")
            if player.split_bet > player.balance:
                raise Exception("Insufficient balance to double down")

            player.balance -= player.split_bet
            player.split_bet *= 2

            player.split_hand.add_card(self.deck.deal(1)[0])
            player.can_double_down = False
            player.can_split = False

            if player.split_hand.is_bust():
                player.split_busted = True
                player.split_result = 'lose'
            else:
                player.split_stood = True

            player.has_acted = True
            self.current_player_turn = self._get_next_player_turn(player_number)
            if self.current_player_turn is None:
                self.phase = 'dealer_turn'
            return

        # Double down on regular hand (or first hand if split)
        if not player.can_double_down:
            raise Exception("Cannot double down")
        if player.current_bet > player.balance:
            raise Exception("Insufficient balance to double down")

        player.balance -= player.current_bet
        player.current_bet *= 2

        player.hand.add_card(self.deck.deal(1)[0])
        player.can_double_down = False
        player.can_split = False

        if player.hand.is_bust():
            player.busted = True
            player.result = 'lose'
        else:
            player.stood = True

        # If has split hand, switch to it
        if player.has_split:
            player.playing_split_hand = True
        else:
            player.has_acted = True
            self.current_player_turn = self._get_next_player_turn(player_number)
            if self.current_player_turn is None:
                self.phase = 'dealer_turn'

    def split(self, player_number: int):
        """Player splits their hand into two separate hands"""
        if self.phase != 'playing':
            raise Exception("Cannot split in current phase")
        if self.current_player_turn != player_number:
            raise Exception("Not your turn")

        player = self.players[player_number]
        if not player.can_split:
            raise Exception("Cannot split this hand")
        if player.current_bet > player.balance:
            raise Exception("Insufficient balance to split")
        if player.has_split:
            raise Exception("Already split (only one split allowed)")

        # Create split hand with second card
        split_card = player.hand.cards.pop(1)
        player.split_hand = BlackjackHand([split_card])

        # Place bet on split hand
        player.balance -= player.current_bet
        player.split_bet = player.current_bet

        # Deal one card to each hand
        player.hand.add_card(self.deck.deal(1)[0])
        player.split_hand.add_card(self.deck.deal(1)[0])

        # Update player state
        player.has_split = True
        player.can_split = False
        player.can_double_down = True  # Can double on first hand after split
        player.playing_split_hand = False  # Start with first hand

        # Check if first hand is blackjack (counts as 21, not blackjack after split)
        if player.hand.is_blackjack():
            player.stood = True

    def hit_split(self, player_number: int):
        """Hit on the split hand (player must finish first hand first)"""
        if self.phase != 'playing':
            raise Exception("Cannot hit in current phase")
        if self.current_player_turn != player_number:
            raise Exception("Not your turn")

        player = self.players[player_number]
        if not player.has_split:
            raise Exception("Player has not split")
        if not player.playing_split_hand:
            raise Exception("Must finish first hand before playing split hand")

        player.split_hand.add_card(self.deck.deal(1)[0])

        # Check if split hand busts
        if player.split_hand.is_bust():
            player.split_busted = True
            player.split_result = 'lose'
            player.has_acted = True
            self.current_player_turn = self._get_next_player_turn(player_number)
            if self.current_player_turn is None:
                self.phase = 'dealer_turn'

    def stand_split(self, player_number: int):
        """Stand on the split hand"""
        if self.phase != 'playing':
            raise Exception("Cannot stand in current phase")
        if self.current_player_turn != player_number:
            raise Exception("Not your turn")

        player = self.players[player_number]
        if not player.has_split:
            raise Exception("Player has not split")
        if not player.playing_split_hand:
            raise Exception("Must finish first hand before standing on split hand")

        player.split_stood = True
        player.has_acted = True

        self.current_player_turn = self._get_next_player_turn(player_number)
        if self.current_player_turn is None:
            self.phase = 'dealer_turn'

    def dealer_play(self):
        """Dealer plays their hand and determines results"""
        if self.phase != 'dealer_turn':
            raise Exception("Not dealer's turn")

        # Dealer must hit on 16 or less, stand on 17 or more
        while self.dealer_hand.calculate_value() < 17:
            self.dealer_hand.add_card(self.deck.deal(1)[0])

        dealer_value = self.dealer_hand.calculate_value()
        dealer_busted = self.dealer_hand.is_bust()
        dealer_blackjack = self.dealer_hand.is_blackjack()

        # Determine each player's result
        for player in self.players.values():
            # Determine first hand result
            if player.result is None:
                player_value = player.hand.calculate_value()
                player_blackjack = player.hand.is_blackjack() and not player.has_split

                if player_blackjack and dealer_blackjack:
                    player.result = 'push'
                    player.balance += player.current_bet  # Return bet
                elif player_blackjack:
                    player.result = 'blackjack'
                    player.balance += int(int(player.current_bet) * 2.5)  # 3:2 payout
                elif dealer_blackjack:
                    player.result = 'lose'
                elif dealer_busted:
                    player.result = 'win'
                    player.balance += player.current_bet * 2
                elif dealer_value > player_value:
                    player.result = 'lose'
                elif player_value > dealer_value:
                    player.result = 'win'
                    player.balance += player.current_bet * 2
                else:
                    player.result = 'push'
                    player.balance += player.current_bet  # Return bet

            # Determine split hand result if exists
            if player.has_split and player.split_result is None:
                split_value = player.split_hand.calculate_value()
                # Split hands cannot get blackjack (21 counts as 21, not blackjack)

                if dealer_blackjack:
                    player.split_result = 'lose'
                elif dealer_busted:
                    player.split_result = 'win'
                    player.balance += player.split_bet * 2
                elif dealer_value > split_value:
                    player.split_result = 'lose'
                elif split_value > dealer_value:
                    player.split_result = 'win'
                    player.balance += player.split_bet * 2
                else:
                    player.split_result = 'push'
                    player.balance += player.split_bet  # Return bet

        self.phase = 'round_over'
        self.round_active = False

    def to_dict(self, include_deck: bool = False) -> Dict:
        """Convert game state to dictionary

        Args:
            include_deck: If True, includes deck in output (for DynamoDB storage).
                         If False, excludes deck (for WebSocket payload reduction).
        """
        result = {
            'dealer_hand': self.dealer_hand.to_dict(),
            'players': {str(num): player.to_dict() for num, player in self.players.items()},
            'phase': self.phase,
            'current_player_turn': self.current_player_turn,
            'round_active': self.round_active,
            'cards_remaining': len(self.deck.cards)
        }

        # Only include deck for DynamoDB storage, not for WebSocket responses
        if include_deck:
            result['deck'] = [card.to_dict() for card in self.deck.cards]

        return result

    @staticmethod
    def from_dict(data: Dict) -> 'BlackjackGameState':
        """Create game state from dictionary"""
        state = BlackjackGameState()
        state.deck.cards = [Card.from_dict(c) for c in data.get('deck', [])]
        state.dealer_hand = BlackjackHand.from_dict(data['dealer_hand'])

        # Restore players
        players_data = data.get('players', {})
        for player_num_str, player_data in players_data.items():
            player_num = int(player_num_str)
            state.players[player_num] = PlayerState.from_dict(player_data)

        state.phase = data['phase']
        state.current_player_turn = data.get('current_player_turn')
        state.round_active = data.get('round_active', False)
        return state