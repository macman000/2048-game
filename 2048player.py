import time
import math
import sys
import traceback
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout, Error as PWError

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG — edit these if needed
# ─────────────────────────────────────────────────────────────────────────────

# TARGET_URL   = "https://macman000.github.io/2048-game/"
# To use your local file instead:
TARGET_URL = "file:///C:/Users/macme/Downloads/2048.html"

MOVE_DELAY   = 0.12   # seconds between moves
MAX_RETRIES  = 5      # how many times to retry a crashed browser before giving up
PAGE_TIMEOUT = 15000  # ms — how long to wait for page load

# ─────────────────────────────────────────────────────────────────────────────
# BOARD LOGIC
# ─────────────────────────────────────────────────────────────────────────────

def slide_row_left(row):
    """Slide and merge one row left. Returns (new_row, score)."""
    tiles = [x for x in row if x]
    score = 0
    merged = []
    i = 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            val = tiles[i] * 2
            merged.append(val)
            score += val
            i += 2
        else:
            merged.append(tiles[i])
            i += 1
    merged += [0] * (4 - len(merged))
    return merged, score

def move_board(board, direction):
    """Apply a move. Returns (new_board, score, moved)."""
    score = 0
    nb = [row[:] for row in board]

    if direction == 'left':
        for r in range(4):
            nb[r], s = slide_row_left(nb[r]); score += s
    elif direction == 'right':
        for r in range(4):
            rev, s = slide_row_left(nb[r][::-1]); nb[r] = rev[::-1]; score += s
    elif direction == 'up':
        for c in range(4):
            col = [nb[r][c] for r in range(4)]
            slid, s = slide_row_left(col)
            for r in range(4): nb[r][c] = slid[r]
            score += s
    elif direction == 'down':
        for c in range(4):
            col = [nb[r][c] for r in range(4)]
            rev, s = slide_row_left(col[::-1]); rev = rev[::-1]
            for r in range(4): nb[r][c] = rev[r]
            score += s

    return nb, score, nb != board

def empty_cells(board):
    return [(r, c) for r in range(4) for c in range(4) if board[r][c] == 0]

def validate_board(board):
    """Raise ValueError if board is not a valid 4x4 grid of non-negative ints."""
    if not isinstance(board, list) or len(board) != 4:
        raise ValueError(f"Board must be 4 rows, got: {type(board).__name__} len={len(board) if isinstance(board, list) else '?'}")
    for i, row in enumerate(board):
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError(f"Row {i} must have 4 cells, got: {row}")
        for j, cell in enumerate(row):
            if not isinstance(cell, (int, float)) or cell < 0:
                raise ValueError(f"Cell [{i}][{j}] invalid: {cell!r}")

# ─────────────────────────────────────────────────────────────────────────────
# HEURISTIC & AI
# ─────────────────────────────────────────────────────────────────────────────

WEIGHTS = [
    [2**15, 2**14, 2**13, 2**12],
    [2**8,  2**9,  2**10, 2**11],
    [2**7,  2**6,  2**5,  2**4],
    [2**0,  2**1,  2**2,  2**3],
]

def heuristic(board):
    empty = len(empty_cells(board))
    snake = sum(board[r][c] * WEIGHTS[r][c] for r in range(4) for c in range(4))
    smoothness = 0
    for r in range(4):
        for c in range(4):
            v = board[r][c]
            if v:
                for dr, dc in [(0, 1), (1, 0)]:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < 4 and 0 <= nc < 4 and board[nr][nc]:
                        smoothness -= abs(math.log2(v) - math.log2(board[nr][nc]))
    mono = 0
    for r in range(4):
        row = [board[r][c] for c in range(4) if board[r][c]]
        if row == sorted(row) or row == sorted(row, reverse=True):
            mono += sum(row)
    for c in range(4):
        col = [board[r][c] for r in range(4) if board[r][c]]
        if col == sorted(col) or col == sorted(col, reverse=True):
            mono += sum(col)
    return snake + smoothness * 10 + empty * 500 + mono * 2

DIRECTIONS = ['left', 'right', 'up', 'down']

def expectimax(board, depth, is_player):
    if depth == 0:
        return heuristic(board)
    if is_player:
        best = -math.inf
        any_move = False
        for d in DIRECTIONS:
            nb, _, moved = move_board(board, d)
            if not moved:
                continue
            any_move = True
            val = expectimax(nb, depth - 1, False)
            if val > best:
                best = val
        return best if any_move else heuristic(board)
    else:
        empties = empty_cells(board)
        if not empties:
            return heuristic(board)
        sample = empties if len(empties) <= 4 else empties[::max(1, len(empties) // 4)]
        total = 0
        for (r, c) in sample:
            for val, prob in [(2, 0.9), (4, 0.1)]:
                b = [row[:] for row in board]
                b[r][c] = val
                total += prob * expectimax(b, depth - 1, True)
        return total / len(sample)

def best_move(board):
    """Return the best direction using expectimax. Falls back to 'down' on any error."""
    try:
        validate_board(board)
    except ValueError as e:
        print(f"  [AI] Invalid board — falling back to 'down': {e}")
        return 'down'

    try:
        best_score = -math.inf
        best_dir   = 'down'
        empties    = len(empty_cells(board))
        depth      = 4 if empties >= 6 else 3 if empties >= 3 else 2

        for d in DIRECTIONS:
            nb, _, moved = move_board(board, d)
            if not moved:
                continue
            score = expectimax(nb, depth, False)
            if score > best_score:
                best_score = score
                best_dir   = d

        return best_dir

    except RecursionError:
        print("  [AI] Recursion limit hit — falling back to 'down'.")
        return 'down'
    except Exception as e:
        print(f"  [AI] Expectimax crashed — falling back to 'down': {e}")
        return 'down'

# ─────────────────────────────────────────────────────────────────────────────
# BOARD READING
# ─────────────────────────────────────────────────────────────────────────────

def read_board(page):
    """
    Read the board from window.cells (our custom game exposes this).
    Returns a 4x4 list of ints, or None if unreadable.
    Raises RuntimeError if the page itself is gone.
    """
    if page.is_closed():
        raise RuntimeError("Page is closed.")

    try:
        raw = page.evaluate("""
            () => {
                if (window.cells && Array.isArray(window.cells)) {
                    return window.cells.map(row => row.map(t => (t && t.value) ? t.value : 0));
                }
                return null;
            }
        """)
    except PWTimeout:
        print("  [Board] JS evaluate timed out.")
        return None
    except PWError as e:
        msg = str(e).lower()
        if "closed" in msg or "destroyed" in msg or "detached" in msg:
            raise RuntimeError(f"Page/context gone: {e}")
        print(f"  [Board] Playwright error: {e}")
        return None
    except Exception as e:
        print(f"  [Board] Unexpected JS error: {e}")
        return None

    if raw is None:
        return None

    try:
        validate_board(raw)
        return [[int(raw[r][c]) for c in range(4)] for r in range(4)]
    except ValueError as e:
        print(f"  [Board] Malformed board data: {e}")
        return None

# ─────────────────────────────────────────────────────────────────────────────
# GAME-OVER / RESTART
# ─────────────────────────────────────────────────────────────────────────────

RETRY_SELECTORS = [
    '.retry-button',
    '.restart-button',
    '#retry-button',
    '[class*="retry"]',
    '[class*="restart"]',
]

def check_and_restart(page, move_count, game_count):
    """
    Check if game is over and restart if so.
    Returns (restarted, new_move_count, new_game_count).
    Raises RuntimeError if the page is gone.
    """
    if page.is_closed():
        raise RuntimeError("Page closed during restart check.")

    # Check window.over flag our game sets
    game_over = False
    try:
        game_over = page.evaluate("() => window.over === true")
    except PWError as e:
        if "closed" in str(e).lower():
            raise RuntimeError(f"Page gone during game-over check: {e}")
        print(f"  [Restart] Could not read window.over (non-fatal): {e}")
    except Exception as e:
        print(f"  [Restart] Unexpected error reading window.over: {e}")

    # Also check for visible retry buttons as a belt-and-braces fallback
    if not game_over:
        for sel in RETRY_SELECTORS:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    game_over = True
                    break
            except Exception:
                continue

    if not game_over:
        return False, move_count, game_count

    game_count += 1
    print(f"\n{'─'*50}")
    print(f"  GAME OVER — Game #{game_count} finished after {move_count} moves.")
    print(f"{'─'*50}\n")

    restarted = False

    # 1. Try N key (our custom game supports it)
    try:
        page.keyboard.press('n')
        time.sleep(0.5)
        restarted = True
        print("  [Restart] Restarted via N key.")
    except Exception as e:
        print(f"  [Restart] N key failed: {e}")

    # 2. Try clicking known selectors
    if not restarted:
        for sel in RETRY_SELECTORS:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(0.8)
                    restarted = True
                    print(f"  [Restart] Restarted via '{sel}'.")
                    break
            except Exception as e:
                print(f"  [Restart] Selector '{sel}' failed: {e}")

    # 3. Last resort: reload the page
    if not restarted:
        print("  [Restart] No button found — reloading page...")
        try:
            page.reload(wait_until="load", timeout=PAGE_TIMEOUT)
            time.sleep(1)
            page.mouse.click(200, 400)
            restarted = True
            print("  [Restart] Page reloaded successfully.")
        except PWTimeout:
            raise RuntimeError("Page reload timed out — session unrecoverable.")
        except Exception as e:
            raise RuntimeError(f"Page reload failed: {e}")

    return True, 0, game_count

# ─────────────────────────────────────────────────────────────────────────────
# SESSION LOOP
# ─────────────────────────────────────────────────────────────────────────────

DIR_TO_KEY     = {'left': 'ArrowLeft', 'right': 'ArrowRight', 'up': 'ArrowUp', 'down': 'ArrowDown'}
FALLBACK_CYCLE = ['ArrowDown', 'ArrowRight', 'ArrowDown', 'ArrowLeft']
MAX_CONSECUTIVE_READ_FAILS = 10

def run_session(page, session_num):
    """Run one browser session until the page closes or an unrecoverable error occurs."""
    print(f"\n{'='*50}")
    print(f"  SESSION {session_num} — {TARGET_URL}")
    print(f"{'='*50}\n")

    try:
        page.goto(TARGET_URL, wait_until="load", timeout=PAGE_TIMEOUT)
    except PWTimeout:
        raise RuntimeError(f"Page load timed out ({PAGE_TIMEOUT}ms).")
    except PWError as e:
        raise RuntimeError(f"Failed to load page: {e}")

    time.sleep(1)

    try:
        page.mouse.click(200, 400)
    except Exception as e:
        print(f"  [Init] Focus click failed (non-fatal): {e}")

    print("  AI is now playing...\n")

    move_count            = 0
    game_count            = 0
    fallback_idx          = 0
    consecutive_failures  = 0

    while not page.is_closed():

        # ── Restart check ──────────────────────────────────────────────────
        try:
            restarted, move_count, game_count = check_and_restart(page, move_count, game_count)
            if restarted:
                consecutive_failures = 0
                fallback_idx = 0
                continue
        except RuntimeError:
            raise
        except Exception as e:
            print(f"  [Loop] Restart check error (non-fatal): {e}")

        # ── Read board ─────────────────────────────────────────────────────
        board = None
        try:
            board = read_board(page)
        except RuntimeError:
            raise
        except Exception as e:
            print(f"  [Loop] Unexpected read error: {e}")

        # ── Pick move ──────────────────────────────────────────────────────
        if board is not None:
            consecutive_failures = 0
            try:
                direction = best_move(board)
                key       = DIR_TO_KEY[direction]
            except KeyError as e:
                print(f"  [Loop] Unknown direction {e!r} — using 'down'.")
                key = 'ArrowDown'
            except Exception as e:
                print(f"  [Loop] Move selection error: {e}")
                key = 'ArrowDown'
        else:
            consecutive_failures += 1
            if consecutive_failures == 1:
                print("  [Loop] Board unreadable — switching to fallback strategy.")
            elif consecutive_failures % MAX_CONSECUTIVE_READ_FAILS == 0:
                print(f"  [Loop] {consecutive_failures} consecutive read failures.")
            key = FALLBACK_CYCLE[fallback_idx % len(FALLBACK_CYCLE)]
            fallback_idx += 1

        # ── Send key ───────────────────────────────────────────────────────
        try:
            page.keyboard.press(key)
        except PWError as e:
            if "closed" in str(e).lower() or "destroyed" in str(e).lower():
                print("  [Loop] Page closed while pressing key — ending session.")
                return
            print(f"  [Loop] Key press error (non-fatal): {e}")
        except Exception as e:
            print(f"  [Loop] Unexpected key press error: {e}")

        move_count += 1

        # ── Periodic status print ──────────────────────────────────────────
        if move_count % 50 == 0 and board is not None:
            try:
                max_tile = max(board[r][c] for r in range(4) for c in range(4))
                print(f"  Move {move_count:>5} | Max tile: {max_tile:>5} | Games: {game_count}")
            except Exception:
                pass

        time.sleep(MOVE_DELAY)

# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

def main():
    attempt = 0

    while attempt < MAX_RETRIES:
        attempt += 1
        print(f"\n{'#'*50}")
        print(f"  BROWSER ATTEMPT {attempt} / {MAX_RETRIES}")
        print(f"{'#'*50}")

        browser = None
        try:
            with sync_playwright() as p:

                # Launch browser
                try:
                    browser = p.chromium.launch(headless=False)
                except Exception as e:
                    print(f"  [Browser] Failed to launch Chromium: {e}")
                    print("  Tip: run  python -m playwright install chromium")
                    time.sleep(3)
                    continue

                # Open page
                try:
                    page = browser.new_page()
                except Exception as e:
                    print(f"  [Browser] Failed to open new tab: {e}")
                    time.sleep(2)
                    continue

                # Run session
                try:
                    run_session(page, attempt)
                    # run_session returned normally = user closed the window
                    print("\n  Window closed by user. Exiting.")
                    sys.exit(0)

                except RuntimeError as e:
                    print(f"\n  [Session] Session crashed: {e}")
                    print(f"  Retrying in 3s... ({attempt}/{MAX_RETRIES})")
                    time.sleep(3)

                except KeyboardInterrupt:
                    print("\n  Stopped by user.")
                    sys.exit(0)

                except Exception as e:
                    print(f"\n  [Session] Unexpected error: {e}")
                    traceback.print_exc()
                    print(f"  Retrying in 3s...")
                    time.sleep(3)

        except KeyboardInterrupt:
            print("\n  Stopped by user.")
            sys.exit(0)

        except Exception as e:
            print(f"  [Playwright] Top-level error: {e}")
            traceback.print_exc()
            time.sleep(3)

        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    print(f"\n  Reached max retries ({MAX_RETRIES}). Giving up.")
    sys.exit(1)


if __name__ == '__main__':
    main()