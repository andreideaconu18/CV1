/* App: PeerJS networking + UI for Liar's Poker.
   Architecture: host runs the simulation; clients are dumb renderers.
   Each state update is computed by the host and sent as a per-player view. */
(function () {
  'use strict';

  const G = window.GameLogic;
  const $ = id => document.getElementById(id);

  const SCREENS = ['lobby', 'waiting', 'game', 'gameover'];
  function showScreen(name) {
    SCREENS.forEach(s => $(s).classList.toggle('active', s === name));
  }

  // --- Globals ---
  let myPeer = null;
  let myId = '';
  let myName = '';
  let isHost = false;
  let mode = 'multi'; // 'multi' | 'solo'
  let hostConn = null;          // (client) connection to host
  const clients = {};            // (host) peerId -> DataConnection
  let state = null;              // (host) authoritative state
  let view = null;               // last received/computed view

  // --- Room code helpers ---
  // Use 'lp-' prefix to namespace on the public PeerJS broker. Display short code.
  const CODE_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  function genCode() {
    let s = '';
    for (let i = 0; i < 5; i++) s += CODE_CHARS[Math.floor(Math.random() * CODE_CHARS.length)];
    return s;
  }
  const peerIdOf = code => 'lp-' + code.toLowerCase();
  const codeOf = peerId => peerId.replace(/^lp-/, '').toUpperCase();

  // --- Lobby wiring ---
  $('btn-create').onclick = onCreate;
  $('btn-join').onclick = onJoin;
  $('btn-solo').onclick = onPlaySolo;
  $('btn-copy').onclick = () => {
    const u = $('share-url');
    u.select();
    try { document.execCommand('copy'); } catch (e) {}
    $('btn-copy').textContent = 'Copied!';
    setTimeout(() => { $('btn-copy').textContent = 'Copy'; }, 1500);
  };
  $('btn-start').onclick = onStartGame;
  $('btn-announce').onclick = onAnnounce;
  $('btn-trombon').onclick = onTrombon;
  $('btn-next-round').onclick = onNextRound;
  $('btn-replay').onclick = () => { location.href = location.pathname; };

  // Auto-fill room code from URL
  const urlParams = new URLSearchParams(location.search);
  if (urlParams.has('room')) {
    $('join-code').value = urlParams.get('room').toUpperCase();
    $('name-input').focus();
  }

  function showError(msg) { $('lobby-error').textContent = msg; }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  }

  // --- Create room (host) ---
  function onCreate() {
    const name = $('name-input').value.trim();
    if (!name) { showError('Enter your name first'); return; }
    showError('');
    myName = name;
    isHost = true;
    $('btn-create').disabled = true;
    $('btn-create').textContent = 'Creating...';
    tryHost(0);
  }

  function tryHost(attempt) {
    if (attempt > 6) {
      showError('Could not create a room. Try again.');
      $('btn-create').disabled = false;
      $('btn-create').textContent = 'Create room';
      return;
    }
    const code = genCode();
    const peer = new Peer(peerIdOf(code), { debug: 1 });
    let opened = false;
    peer.on('open', id => {
      opened = true;
      myPeer = peer;
      myId = id;
      onHostReady(id);
    });
    peer.on('error', err => {
      console.error('peer error', err);
      if (!opened && (err.type === 'unavailable-id' || err.type === 'network')) {
        peer.destroy();
        tryHost(attempt + 1);
      } else if (!opened) {
        showError('Network error: ' + err.type);
        $('btn-create').disabled = false;
        $('btn-create').textContent = 'Create room';
      }
    });
    peer.on('connection', conn => onClientConnect(conn));
  }

  function onHostReady(id) {
    state = {
      phase: 'lobby',
      players: [{ id, name: myName, count: 1, eliminated: false, cards: [] }],
      lastHand: null,
      history: [],
      activeId: null,
      startingId: id,
      result: null,
      winnerId: null,
      log: [],
    };
    const code = codeOf(id);
    $('room-display').textContent = code;
    $('share-url').value = location.origin + location.pathname + '?room=' + code;
    showScreen('waiting');
    renderWaiting();
  }

  // --- Join room (client) ---
  function onJoin() {
    const name = $('name-input').value.trim();
    let code = $('join-code').value.trim().toUpperCase();
    if (!name) { showError('Enter your name first'); return; }
    if (!code) { showError('Enter a room code'); return; }
    showError('');
    myName = name;
    isHost = false;
    $('btn-join').disabled = true;
    $('btn-join').textContent = 'Connecting...';

    const peer = new Peer({ debug: 1 });
    let timer = setTimeout(() => {
      if (!myPeer || !hostConn || !hostConn.open) {
        showError('Could not connect. Check the room code.');
        $('btn-join').disabled = false;
        $('btn-join').textContent = 'Join';
        try { peer.destroy(); } catch (e) {}
      }
    }, 8000);

    peer.on('open', id => {
      myPeer = peer;
      myId = id;
      const conn = peer.connect(peerIdOf(code), { reliable: true });
      hostConn = conn;
      conn.on('open', () => {
        clearTimeout(timer);
        $('btn-join').disabled = false;
        $('btn-join').textContent = 'Join';
        conn.send({ type: 'hello', name: myName });
      });
      conn.on('data', onHostMessage);
      conn.on('close', () => {
        alert('Disconnected from host.');
        location.href = location.pathname;
      });
    });
    peer.on('error', err => {
      console.error('peer error', err);
      clearTimeout(timer);
      if (err.type === 'peer-unavailable') {
        showError('Room not found. Check the code.');
      } else {
        showError('Network error: ' + err.type);
      }
      $('btn-join').disabled = false;
      $('btn-join').textContent = 'Join';
    });
  }

  // --- Host: handle incoming client connections & messages ---
  function onClientConnect(conn) {
    conn.on('data', msg => {
      if (msg.type === 'hello') {
        if (!state || state.phase !== 'lobby') {
          conn.send({ type: 'rejected', reason: 'Game already in progress.' });
          setTimeout(() => conn.close(), 200);
          return;
        }
        if (state.players.some(p => p.id === conn.peer)) return;
        const safeName = String(msg.name || 'Player').slice(0, 20) || 'Player';
        state.players.push({ id: conn.peer, name: safeName, count: 1, eliminated: false, cards: [] });
        clients[conn.peer] = conn;
        renderWaiting();
        broadcastState();
      } else if (msg.type === 'announce') {
        handleAnnounce(conn.peer, msg.hand);
      } else if (msg.type === 'trombon') {
        handleTrombon(conn.peer);
      } else if (msg.type === 'nextRound') {
        if (state && state.phase === 'reveal') startRound();
      }
    });
    conn.on('close', () => onClientDisconnect(conn.peer));
  }

  function onClientDisconnect(peerId) {
    delete clients[peerId];
    if (!state) return;
    const idx = state.players.findIndex(p => p.id === peerId);
    if (idx === -1) return;
    const wasActive = state.activeId === peerId;
    const dcName = state.players[idx].name;
    state.players.splice(idx, 1);
    if (state.phase !== 'lobby') {
      state.log.push(`${dcName} disconnected.`);
      if (wasActive && state.phase === 'announce') advanceTurn();
      const alive = alivePlayers();
      if (alive.length <= 1) {
        state.phase = 'gameover';
        state.winnerId = alive[0]?.id || null;
      }
    }
    broadcastState();
    renderWaiting();
  }

  // --- Solo mode (vs bots) ---
  const BOT_NAMES = ['Trombónel', 'Bluffius', 'Cardinel', 'Mister Liar'];

  function onPlaySolo() {
    const name = $('name-input').value.trim();
    if (!name) { showError('Enter your name first'); return; }
    showError('');
    const botCount = Math.max(1, Math.min(4, parseInt($('bot-count').value, 10) || 2));
    myName = name;
    isHost = true;
    mode = 'solo';
    myId = 'me';

    state = {
      phase: 'lobby',
      players: [{ id: myId, name: myName, count: 1, eliminated: false, cards: [] }],
      lastHand: null,
      history: [],
      activeId: null,
      startingId: myId,
      result: null,
      winnerId: null,
      log: [],
    };
    for (let i = 0; i < botCount; i++) {
      state.players.push({
        id: 'bot-' + i,
        name: BOT_NAMES[i] || `Bot ${i + 1}`,
        count: 1,
        eliminated: false,
        cards: [],
      });
    }
    state.startingId = myId;
    startRound();
  }

  function maybeBotTurn() {
    if (mode !== 'solo' || !state || state.phase !== 'announce') return;
    if (typeof state.activeId !== 'string' || !state.activeId.startsWith('bot-')) return;
    const bot = findPlayer(state.activeId);
    if (!bot || bot.eliminated) return;
    setTimeout(() => {
      if (state.activeId !== bot.id || state.phase !== 'announce') return;
      const decision = decideBotMove(bot);
      if (decision.type === 'trombon') handleTrombon(bot.id);
      else handleAnnounce(bot.id, decision.hand);
    }, 900 + Math.random() * 1100);
  }

  function decideBotMove(bot) {
    const otherCount = state.players
      .filter(p => p.id !== bot.id && !p.eliminated)
      .reduce((s, p) => s + p.count, 0);

    if (state.lastHand) {
      const prob = estimateHandProb(state.lastHand, bot.cards, otherCount);
      const callThresh = 0.30 + Math.random() * 0.15;
      if (prob < callThresh) return { type: 'trombon' };
    }

    const candidates = enumerateHandsStrongerThan(state.lastHand);
    if (candidates.length === 0) {
      return state.lastHand
        ? { type: 'trombon' }
        : { type: 'announce', hand: { category: G.CAT.HIGH_CARD, ranks: [2] } };
    }

    const safeThresh = 0.55 + Math.random() * 0.20;
    let pick = null;
    let bluffPick = candidates[0];
    for (const h of candidates) {
      const p = estimateHandProb(h, bot.cards, otherCount);
      if (p >= safeThresh) { pick = h; break; }
    }
    return { type: 'announce', hand: pick || bluffPick };
  }

  let _allHandsCache = null;
  function allEnumeratedHands() {
    if (_allHandsCache) return _allHandsCache;
    const all = [];
    for (let r = 2; r <= 14; r++) all.push({ category: G.CAT.HIGH_CARD, ranks: [r] });
    for (let r = 2; r <= 14; r++) all.push({ category: G.CAT.PAIR, ranks: [r] });
    for (let h = 3; h <= 14; h++) for (let l = 2; l < h; l++)
      all.push({ category: G.CAT.TWO_PAIR, ranks: [h, l] });
    for (let r = 2; r <= 14; r++) all.push({ category: G.CAT.THREE, ranks: [r] });
    for (let r = 5; r <= 14; r++) all.push({ category: G.CAT.STRAIGHT, ranks: [r] });
    for (let r = 2; r <= 14; r++) all.push({ category: G.CAT.FLUSH, ranks: [r] });
    for (let t = 2; t <= 14; t++) for (let p = 2; p <= 14; p++) if (t !== p)
      all.push({ category: G.CAT.FULL_HOUSE, ranks: [t, p] });
    for (let r = 2; r <= 14; r++) all.push({ category: G.CAT.FOUR, ranks: [r] });
    for (let r = 5; r <= 14; r++) all.push({ category: G.CAT.STRAIGHT_FLUSH, ranks: [r] });
    all.sort(G.compareHands);
    _allHandsCache = all;
    return all;
  }

  function enumerateHandsStrongerThan(lastHand) {
    const all = allEnumeratedHands();
    if (!lastHand) return all.slice();
    return all.filter(h => G.compareHands(h, lastHand) > 0);
  }

  // Monte Carlo: probability that `hand` exists in a pool of (myCards ∪ otherCount random cards)
  function estimateHandProb(hand, myCards, otherCount) {
    if (otherCount <= 0) return G.handExists(hand, myCards) ? 1 : 0;
    const myKeys = new Set(myCards.map(c => c.rank + ':' + c.suit));
    const remaining = G.newDeck().filter(c => !myKeys.has(c.rank + ':' + c.suit));
    const N = 120;
    let hits = 0;
    for (let i = 0; i < N; i++) {
      const arr = remaining.slice();
      // partial Fisher-Yates: pick `otherCount` random distinct cards
      for (let k = 0; k < otherCount; k++) {
        const j = k + Math.floor(Math.random() * (arr.length - k));
        [arr[k], arr[j]] = [arr[j], arr[k]];
      }
      const pool = myCards.concat(arr.slice(0, otherCount));
      if (G.handExists(hand, pool)) hits++;
    }
    return hits / N;
  }

  // --- Host: lobby ---
  function renderWaiting() {
    if (!isHost) return;
    const ul = $('players-list');
    ul.innerHTML = '';
    state.players.forEach(p => {
      const li = document.createElement('li');
      const tag = p.id === myId ? ' <span class="muted small">(you, host)</span>' : '';
      li.innerHTML = `<span>${escapeHtml(p.name)}${tag}</span>`;
      ul.appendChild(li);
    });
    $('btn-start').disabled = state.players.length < 2;
  }

  // --- Host: gameplay ---
  function alivePlayers() { return state.players.filter(p => !p.eliminated); }
  function findPlayer(id) { return state.players.find(p => p.id === id); }

  function nextAliveAfter(fromId) {
    // walk full ordered player list from fromId+1, wrap, skip eliminated
    const n = state.players.length;
    let i = state.players.findIndex(p => p.id === fromId);
    if (i === -1) i = 0;
    for (let k = 1; k <= n; k++) {
      const p = state.players[(i + k) % n];
      if (!p.eliminated) return p.id;
    }
    return fromId;
  }

  function advanceTurn() {
    state.activeId = nextAliveAfter(state.activeId);
  }

  function onStartGame() {
    if (!isHost || state.phase !== 'lobby' || state.players.length < 2) return;
    state.startingId = state.players[0].id;
    startRound();
  }

  function startRound() {
    state.phase = 'announce';
    state.lastHand = null;
    state.history = [];
    state.result = null;
    const deck = G.shuffle(G.newDeck());
    let idx = 0;
    state.players.forEach(p => {
      if (p.eliminated) { p.cards = []; return; }
      p.cards = deck.slice(idx, idx + p.count);
      idx += p.count;
    });
    let starter = findPlayer(state.startingId);
    if (!starter || starter.eliminated) {
      starter = alivePlayers()[0];
      state.startingId = starter.id;
    }
    state.activeId = state.startingId;
    state.log.push(`— New round — ${starter.name} starts (${alivePlayers().reduce((s, p) => s + p.count, 0)} cards in play)`);
    broadcastState();
  }

  function validHand(hand) {
    if (!hand || typeof hand.category !== 'number' || !Array.isArray(hand.ranks)) return false;
    for (const r of hand.ranks) if (typeof r !== 'number' || r < 2 || r > 14) return false;
    switch (hand.category) {
      case G.CAT.HIGH_CARD:
      case G.CAT.PAIR:
      case G.CAT.THREE:
      case G.CAT.FOUR:
      case G.CAT.FLUSH:
        return hand.ranks.length === 1;
      case G.CAT.STRAIGHT:
      case G.CAT.STRAIGHT_FLUSH:
        return hand.ranks.length === 1 && hand.ranks[0] >= 5 && hand.ranks[0] <= 14;
      case G.CAT.TWO_PAIR:
        return hand.ranks.length === 2 && hand.ranks[0] > hand.ranks[1];
      case G.CAT.FULL_HOUSE:
        return hand.ranks.length === 2 && hand.ranks[0] !== hand.ranks[1];
      default:
        return false;
    }
  }

  function handleAnnounce(playerId, hand) {
    if (!state || state.phase !== 'announce') return;
    if (state.activeId !== playerId) return;
    if (!validHand(hand)) return;
    if (state.lastHand && G.compareHands(hand, state.lastHand) <= 0) return;
    state.lastHand = hand;
    state.history.push({ playerId, hand });
    state.log.push(`${findPlayer(playerId).name}: ${G.handLabel(hand)}`);
    advanceTurn();
    broadcastState();
  }

  function handleTrombon(playerId) {
    if (!state || state.phase !== 'announce') return;
    if (state.activeId !== playerId) return;
    if (!state.lastHand) return; // first to act can't call

    state.phase = 'reveal';
    const pool = state.players.flatMap(p => p.cards);
    const exists = G.handExists(state.lastHand, pool);
    const lastEntry = state.history[state.history.length - 1];
    const loserId = exists ? playerId : lastEntry.playerId;
    const loser = findPlayer(loserId);
    const caller = findPlayer(playerId);
    loser.count += 1;
    let eliminated = false;
    if (loser.count > 5) {
      loser.eliminated = true;
      loser.count = 5;
      eliminated = true;
    }
    state.result = {
      loserId, hand: state.lastHand, exists,
      claimerId: playerId, eliminated,
    };
    const verdict = exists ? 'EXISTS' : 'does NOT exist';
    state.log.push(
      `${caller.name} called Trombón! ${G.handLabel(state.lastHand)} ${verdict} → ${loser.name} ` +
      (eliminated ? 'is OUT' : `now has ${loser.count} cards`)
    );

    const alive = alivePlayers();
    if (alive.length <= 1) {
      state.phase = 'gameover';
      state.winnerId = alive[0]?.id || null;
    } else {
      state.startingId = eliminated ? nextAliveAfter(loserId) : loserId;
    }
    broadcastState();
  }

  function onNextRound() {
    if (isHost) {
      if (state && state.phase === 'reveal') startRound();
    } else if (hostConn && hostConn.open) {
      hostConn.send({ type: 'nextRound' });
    }
  }

  // --- Host: broadcast ---
  function broadcastState() {
    if (!isHost) return;
    if (mode === 'multi') {
      for (const pid in clients) {
        const c = clients[pid];
        if (c && c.open) c.send({ type: 'state', view: makeView(pid) });
      }
    }
    onHostMessage({ type: 'state', view: makeView(myId) });
    if (mode === 'solo') maybeBotTurn();
  }

  function makeView(forId) {
    const me = state.players.find(p => p.id === forId);
    const showAll = state.phase === 'reveal' || state.phase === 'gameover';
    return {
      phase: state.phase,
      players: state.players.map(p => ({
        id: p.id, name: p.name, count: p.count, eliminated: p.eliminated,
      })),
      myId: forId,
      myCards: me ? me.cards.slice() : [],
      activeId: state.activeId,
      lastHand: state.lastHand,
      history: state.history,
      result: state.result,
      revealedCards: showAll
        ? Object.fromEntries(state.players.map(p => [p.id, p.cards.slice()]))
        : null,
      winnerId: state.winnerId,
      log: state.log.slice(-60),
      shareCode: codeOf(myId),
    };
  }

  // --- Client/host: receive state ---
  function onHostMessage(msg) {
    if (msg.type === 'state') {
      view = msg.view;
      render(view);
    } else if (msg.type === 'rejected') {
      alert('Cannot join: ' + msg.reason);
      location.href = location.pathname;
    }
  }

  // --- Render ---
  function render(v) {
    if (!v) return;
    if (v.phase === 'lobby') {
      // Clients see the waiting screen with a player list (no host controls).
      if (!isHost) renderClientWaiting(v);
      return;
    }
    if (v.phase === 'gameover') {
      const winner = v.players.find(p => p.id === v.winnerId);
      $('winner-msg').textContent = winner
        ? (winner.id === v.myId ? `🏆 You win!` : `🏆 ${winner.name} wins!`)
        : 'Game over';
      showScreen('gameover');
      return;
    }
    showScreen('game');
    renderPlayersBar(v);
    renderLastHand(v);
    renderMyCards(v);
    renderRevealAndAction(v);
    renderLog(v);
  }

  function renderClientWaiting(v) {
    showScreen('waiting');
    $('room-display').textContent = v.shareCode || codeOf(hostConn?.peer || '');
    $('share-url').value = location.origin + location.pathname + '?room=' + (v.shareCode || codeOf(hostConn?.peer || ''));
    const ul = $('players-list');
    ul.innerHTML = '';
    v.players.forEach(p => {
      const li = document.createElement('li');
      const tag = p.id === v.myId ? ' <span class="muted small">(you)</span>' : '';
      li.innerHTML = `<span>${escapeHtml(p.name)}${tag}</span>`;
      ul.appendChild(li);
    });
    $('host-controls').classList.add('hidden');
    $('waiting-status').textContent = 'Waiting for the host to start...';
  }

  function renderPlayersBar(v) {
    const bar = $('players-bar');
    bar.innerHTML = '';
    v.players.forEach(p => {
      const div = document.createElement('div');
      const cls = ['player-pill'];
      if (p.id === v.activeId && !p.eliminated) cls.push('active');
      if (p.eliminated) cls.push('eliminated');
      if (p.id === v.myId) cls.push('me');
      div.className = cls.join(' ');
      const dots = '●'.repeat(p.count) + '<span style="opacity:0.3">' + '○'.repeat(Math.max(0, 5 - p.count)) + '</span>';
      div.innerHTML = `<span>${escapeHtml(p.name)}${p.id === v.myId ? ' (you)' : ''}</span><span class="dots">${dots}</span>`;
      bar.appendChild(div);
    });
  }

  function renderLastHand(v) {
    const lh = $('last-hand');
    if (v.lastHand) {
      const last = v.history[v.history.length - 1];
      const lastName = v.players.find(p => p.id === last.playerId)?.name || '';
      lh.innerHTML =
        `<div class="label">Last announce by ${escapeHtml(lastName)}</div>` +
        `<div class="hand">${escapeHtml(G.handLabel(v.lastHand))}</div>`;
    } else {
      const startName = v.players.find(p => p.id === v.activeId)?.name || '';
      lh.innerHTML = `<div class="label">No announcements yet</div>` +
                     `<div class="hand">${escapeHtml(startName)} starts</div>`;
    }
  }

  function renderMyCards(v) {
    const wrap = $('my-cards');
    wrap.innerHTML = '';
    if (!v.myCards || v.myCards.length === 0) {
      wrap.innerHTML = '<p class="muted" style="text-align:center">You are eliminated.</p>';
      return;
    }
    wrap.appendChild(makeCardsRow(v.myCards));
  }

  function renderRevealAndAction(v) {
    const reveal = $('reveal');
    const picker = $('picker');
    const next = $('next-round');
    if (v.phase === 'reveal' && v.revealedCards) {
      reveal.classList.remove('hidden');
      picker.classList.add('hidden');
      next.classList.remove('hidden');
      $('btn-next-round').classList.toggle('hidden', !isHost);

      reveal.innerHTML = '';
      const r = v.result;
      const claimer = v.players.find(p => p.id === r.claimerId);
      const loser = v.players.find(p => p.id === r.loserId);
      const head = document.createElement('div');
      head.id = 'reveal-result';
      head.classList.add(r.exists ? 'exists' : 'absent');
      head.innerHTML =
        `<b>${escapeHtml(claimer.name)}</b> called Trombón!<br>` +
        `<i>${escapeHtml(G.handLabel(r.hand))}</i> ` +
        (r.exists ? '✓ exists' : '✗ does not exist') + '<br>' +
        `<b>${escapeHtml(loser.name)}</b> ` +
        (r.eliminated
          ? `is eliminated.`
          : `now has ${loser.count} card${loser.count === 1 ? '' : 's'}.`);
      reveal.appendChild(head);
      v.players.forEach(p => {
        const cards = v.revealedCards[p.id];
        if (!cards || cards.length === 0) return;
        const row = document.createElement('div');
        row.className = 'player-cards';
        const name = document.createElement('div');
        name.className = 'name';
        name.textContent = p.name;
        row.appendChild(name);
        row.appendChild(makeCardsRow(cards));
        reveal.appendChild(row);
      });
      $('status-msg').textContent = isHost ? 'Click "Next round" when ready.' : 'Waiting for host…';
      return;
    }
    reveal.classList.add('hidden');
    next.classList.add('hidden');

    if (v.phase === 'announce') {
      const myTurn = v.activeId === v.myId;
      const meEliminated = v.players.find(p => p.id === v.myId)?.eliminated;
      if (myTurn && !meEliminated) {
        picker.classList.remove('hidden');
        $('btn-trombon').disabled = !v.lastHand;
        renderPicker(v);
        $('status-msg').textContent = 'Your turn — announce a stronger hand or call Trombón.';
      } else {
        picker.classList.add('hidden');
        const active = v.players.find(p => p.id === v.activeId);
        $('status-msg').textContent = active ? `Waiting for ${active.name}…` : '';
      }
    }
  }

  function renderLog(v) {
    const lg = $('log');
    lg.innerHTML = '';
    v.log.forEach(line => {
      const d = document.createElement('div');
      d.className = 'entry';
      if (line.startsWith('—')) d.classList.add('round');
      if (line.includes('Trombón')) d.classList.add('bust');
      d.textContent = line;
      lg.appendChild(d);
    });
    lg.scrollTop = lg.scrollHeight;
  }

  function makeCardsRow(cards) {
    const row = document.createElement('div');
    row.className = 'cards';
    cards.forEach(c => row.appendChild(makeCard(c)));
    return row;
  }
  function makeCard(c) {
    const d = document.createElement('div');
    d.className = 'card';
    if (c.suit === '♥' || c.suit === '♦') d.classList.add('red');
    d.innerHTML = `<div>${G.RANK_NAMES[c.rank]}</div><div class="suit">${c.suit}</div>`;
    return d;
  }

  // --- Picker UI ---
  let pickerCategory = G.CAT.HIGH_CARD;
  let pickerRanks = [2];

  (function initCategorySelect() {
    const sel = $('cat-select');
    G.CAT_NAMES.forEach((name, i) => {
      const opt = document.createElement('option');
      opt.value = i;
      opt.textContent = name;
      sel.appendChild(opt);
    });
    sel.onchange = () => {
      pickerCategory = +sel.value;
      pickerRanks = defaultRanks(pickerCategory);
      renderPicker(view);
    };
  })();

  function defaultRanks(cat) {
    switch (cat) {
      case G.CAT.STRAIGHT:
      case G.CAT.STRAIGHT_FLUSH:
        return [6];
      case G.CAT.TWO_PAIR: return [3, 2];
      case G.CAT.FULL_HOUSE: return [2, 3];
      default: return [2];
    }
  }

  function renderPicker(v) {
    $('cat-select').value = pickerCategory;
    const area = $('rank-area');
    area.innerHTML = '';
    const cat = pickerCategory;

    function addLabel(t) {
      const s = document.createElement('span');
      s.textContent = t;
      s.style.color = 'var(--muted)';
      area.appendChild(s);
    }

    if (cat === G.CAT.HIGH_CARD || cat === G.CAT.PAIR ||
        cat === G.CAT.THREE || cat === G.CAT.FOUR) {
      area.appendChild(rankSelect(0, 2, 14));
    } else if (cat === G.CAT.FLUSH) {
      addLabel('high ');
      area.appendChild(rankSelect(0, 2, 14));
    } else if (cat === G.CAT.STRAIGHT || cat === G.CAT.STRAIGHT_FLUSH) {
      addLabel('top ');
      area.appendChild(rankSelect(0, 5, 14));
    } else if (cat === G.CAT.TWO_PAIR) {
      addLabel('high ');
      area.appendChild(rankSelect(0, 3, 14));
      addLabel(' over ');
      area.appendChild(rankSelect(1, 2, 13));
    } else if (cat === G.CAT.FULL_HOUSE) {
      addLabel('three ');
      area.appendChild(rankSelect(0, 2, 14));
      addLabel(' over pair ');
      area.appendChild(rankSelect(1, 2, 14));
    }
  }

  function rankSelect(idx, min, max) {
    const sel = document.createElement('select');
    for (let r = min; r <= max; r++) {
      const opt = document.createElement('option');
      opt.value = r;
      opt.textContent = G.RANK_NAMES[r];
      if (pickerRanks[idx] === r) opt.selected = true;
      sel.appendChild(opt);
    }
    sel.onchange = () => { pickerRanks[idx] = +sel.value; };
    return sel;
  }

  function onAnnounce() {
    const hand = { category: pickerCategory, ranks: pickerRanks.slice() };
    if (pickerCategory === G.CAT.TWO_PAIR && hand.ranks[0] <= hand.ranks[1]) {
      alert('High pair must be greater than low pair.');
      return;
    }
    if (pickerCategory === G.CAT.FULL_HOUSE && hand.ranks[0] === hand.ranks[1]) {
      alert('Three and pair must be different ranks.');
      return;
    }
    if (view && view.lastHand && G.compareHands(hand, view.lastHand) <= 0) {
      alert('You must announce a stronger hand than the last one.');
      return;
    }
    if (isHost) handleAnnounce(myId, hand);
    else if (hostConn && hostConn.open) hostConn.send({ type: 'announce', hand });
  }

  function onTrombon() {
    if (!view || !view.lastHand) return;
    if (isHost) handleTrombon(myId);
    else if (hostConn && hostConn.open) hostConn.send({ type: 'trombon' });
  }
})();
