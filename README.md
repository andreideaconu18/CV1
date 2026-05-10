# Liar's Poker (Trombón)

A browser-based multiplayer card game. Romanian *Trombón* with poker hands.

**Play it:** open `index.html` after deployment, or visit the GitHub Pages URL after enabling Pages in repo settings.

## Rules
- Each player starts with 1 card (private).
- Play goes clockwise. On your turn:
  - Announce a poker hand strictly stronger than the previous announce, **or**
  - Call **Trombón!** if you don't believe the previous announce.
- The hand is evaluated against **all players' cards combined**. If the announced hand exists in the combined pool, the caller loses; otherwise the announcer loses.
- Loser gets +1 card next round. **At 5 cards, getting burnt eliminates you.** Last player wins.

## How to host & share
1. One player clicks **Create room** → gets a 5-character code and a shareable URL.
2. Friends open the URL (or paste the code on the lobby) and join.
3. Host clicks **Start game**.

Networking is peer-to-peer via [PeerJS](https://peerjs.com/) public broker — no backend.

## Files
- `index.html` — page shell
- `style.css` — styling
- `game.js` — pure game logic (deck, hand evaluation, comparison)
- `app.js` — UI + PeerJS networking
- `.github/workflows/pages.yml` — auto-deploy to GitHub Pages

## Deploy
The workflow `.github/workflows/pages.yml` deploys on every push to `main` (and `claude/**` branches). To enable:
1. In the repository on GitHub, go to **Settings → Pages**.
2. Set **Source** to **GitHub Actions**.
3. Push (or re-run the workflow). The site will be at `https://<user>.github.io/<repo>/`.
