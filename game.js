/* Pure game logic: deck, hand evaluation, comparison.
   No DOM, no networking. */
(function () {
  'use strict';

  const SUITS = ['♠', '♥', '♦', '♣']; // ♠ ♥ ♦ ♣
  const SUIT_NAMES = { '♠': 'spades', '♥': 'hearts', '♦': 'diamonds', '♣': 'clubs' };
  const RANKS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14];
  const RANK_NAMES = { 2:'2', 3:'3', 4:'4', 5:'5', 6:'6', 7:'7', 8:'8', 9:'9', 10:'10', 11:'J', 12:'Q', 13:'K', 14:'A' };

  const CAT = {
    HIGH_CARD: 0,
    PAIR: 1,
    TWO_PAIR: 2,
    THREE: 3,
    STRAIGHT: 4,
    FLUSH: 5,
    FULL_HOUSE: 6,
    FOUR: 7,
    STRAIGHT_FLUSH: 8,
  };
  const CAT_NAMES = [
    'High Card', 'Pair', 'Two Pair', 'Three of a Kind',
    'Straight', 'Flush', 'Full House', 'Four of a Kind', 'Straight Flush',
  ];

  function newDeck() {
    const deck = [];
    for (const suit of SUITS) {
      for (const rank of RANKS) deck.push({ rank, suit });
    }
    return deck;
  }

  function shuffle(deck) {
    for (let i = deck.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [deck[i], deck[j]] = [deck[j], deck[i]];
    }
    return deck;
  }

  // Compare two hand claims. Returns -1, 0, 1.
  function compareHands(a, b) {
    if (a.category !== b.category) return Math.sign(a.category - b.category);
    for (let i = 0; i < a.ranks.length; i++) {
      if (a.ranks[i] !== b.ranks[i]) return Math.sign(a.ranks[i] - b.ranks[i]);
    }
    return 0;
  }

  // Does the announced hand exist in the combined pool of cards?
  // A claim {category C, ranks V} is satisfied iff the pool contains a hand
  // of category C with strength >= V.
  function handExists(hand, pool) {
    const counts = {};                 // rank -> count
    const suitRanks = { '♠': [], '♥': [], '♦': [], '♣': [] };
    for (const c of pool) {
      counts[c.rank] = (counts[c.rank] || 0) + 1;
      suitRanks[c.suit].push(c.rank);
    }
    for (const s in suitRanks) suitRanks[s].sort((a, b) => a - b);

    const rankSet = new Set(Object.keys(counts).map(Number));

    // Top T means cards T-4..T must all exist. Wheel: top 5 uses A-2-3-4-5.
    function hasStraightAt(top, present) {
      if (top < 5 || top > 14) return false;
      if (top === 5) return [14, 2, 3, 4, 5].every(r => present.has(r));
      return [top - 4, top - 3, top - 2, top - 1, top].every(r => present.has(r));
    }

    switch (hand.category) {
      case CAT.HIGH_CARD: {
        const r = hand.ranks[0];
        for (const k in counts) if (+k >= r) return true;
        return false;
      }
      case CAT.PAIR: {
        const r = hand.ranks[0];
        for (const k in counts) if (+k >= r && counts[k] >= 2) return true;
        return false;
      }
      case CAT.TWO_PAIR: {
        const [hi, lo] = hand.ranks;
        const pairs = Object.entries(counts)
          .filter(([, v]) => v >= 2).map(([k]) => +k).sort((a, b) => b - a);
        if (pairs.length < 2) return false;
        return pairs[0] >= hi && pairs[1] >= lo;
      }
      case CAT.THREE: {
        const r = hand.ranks[0];
        for (const k in counts) if (+k >= r && counts[k] >= 3) return true;
        return false;
      }
      case CAT.STRAIGHT: {
        const top = hand.ranks[0];
        for (let T = 14; T >= top; T--) {
          if (hasStraightAt(T, rankSet)) return true;
        }
        return false;
      }
      case CAT.FLUSH: {
        const r = hand.ranks[0];
        for (const s in suitRanks) {
          const arr = suitRanks[s];
          if (arr.length >= 5 && arr[arr.length - 1] >= r) return true;
        }
        return false;
      }
      case CAT.FULL_HOUSE: {
        const [t, p] = hand.ranks;
        const trips = Object.entries(counts).filter(([k, v]) => +k >= t && v >= 3).map(([k]) => +k);
        for (const rt of trips) {
          for (const k in counts) {
            if (+k !== rt && +k >= p && counts[k] >= 2) return true;
          }
        }
        return false;
      }
      case CAT.FOUR: {
        const r = hand.ranks[0];
        for (const k in counts) if (+k >= r && counts[k] >= 4) return true;
        return false;
      }
      case CAT.STRAIGHT_FLUSH: {
        const top = hand.ranks[0];
        for (const s in suitRanks) {
          const present = new Set(suitRanks[s]);
          for (let T = 14; T >= top; T--) {
            if (hasStraightAt(T, present)) return true;
          }
        }
        return false;
      }
    }
    return false;
  }

  function handLabel(hand) {
    const R = RANK_NAMES;
    switch (hand.category) {
      case CAT.HIGH_CARD: return `High card ${R[hand.ranks[0]]}`;
      case CAT.PAIR: return `Pair of ${R[hand.ranks[0]]}s`;
      case CAT.TWO_PAIR: return `Two pair, ${R[hand.ranks[0]]}s and ${R[hand.ranks[1]]}s`;
      case CAT.THREE: return `Three ${R[hand.ranks[0]]}s`;
      case CAT.STRAIGHT: return `Straight to ${R[hand.ranks[0]]}`;
      case CAT.FLUSH: return `Flush, ${R[hand.ranks[0]]}-high`;
      case CAT.FULL_HOUSE: return `Full house, ${R[hand.ranks[0]]}s over ${R[hand.ranks[1]]}s`;
      case CAT.FOUR: return `Four ${R[hand.ranks[0]]}s`;
      case CAT.STRAIGHT_FLUSH: return `Straight flush to ${R[hand.ranks[0]]}`;
    }
    return '?';
  }

  window.GameLogic = {
    SUITS, SUIT_NAMES, RANKS, RANK_NAMES, CAT, CAT_NAMES,
    newDeck, shuffle, compareHands, handExists, handLabel,
  };
})();
