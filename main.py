import requests
import time
import random
from datetime import datetime, timezone, timedelta
from urllib.parse import unquote
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============================================================
# CONFIGURATION - ALL SETTINGS AT THE TOP
# ============================================================

from dotenv import load_dotenv
import os

load_dotenv()

# ── Cookie ──
COOKIE_STRING = os.getenv("COOKIE_STRING", "")

# Auto market config ID for 5-minute BTC markets
AUTO_MARKET_CONFIG_ID = "cmlpz9rqn0198ky04orxmcaqt"

# Multi-bet stacking amounts (caps for dynamic sizing)
MULTI_BET_AMOUNTS = [5000, 4000, 1000]
MULTI_BET_DELAY = 3        # Seconds between each stacked bet
DYNAMIC_SLIPPAGE = 0.35    # Max allowed slippage (35%)
BALANCE_USAGE_PERCENT = 0.99
ROUND_DOWN_TO = 100
MAX_BUY_RETRIES = 4
BUY_RETRY_SHRINK = 0.80

# Bet configuration
BET_TIMING_SECONDS = 59  # Place bet when this many seconds remaining
POLL_INTERVAL = 0.5      # Ultra-fast polling (0.5 seconds)
MIN_BALANCE = 30000         # Stop bot if balance falls below this

# Active/Inactive cycle configuration
MIN_MARKETS_PER_SESSION = 25
MAX_MARKETS_PER_SESSION = 35
MIN_INACTIVE_HOURS = 0.03  # ~2 minutes
MAX_INACTIVE_HOURS = 0.08  # ~5 minutes

# Proxy configuration (set USE_PROXY = False to connect directly)
USE_PROXY = True
PROXY_HOST="93.190.143.48"
PROXY_PORT="443"
PROXY_USER="fvvgxhcjc1-res-country-DE-state-2951839-city-2867714-hold-query"
PROXY_PASS="JPdh3jkQP1rnzFJi"

# ============================================================
# DO NOT MODIFY BELOW THIS LINE
# ============================================================

LATEST_MARKET_URL = f"https://markets.vault777.com/api/auto-markets/{AUTO_MARKET_CONFIG_ID}/latest"
BASE_MARKET_URL = "https://markets.vault777.com/api/markets/"
BUY_URL = "https://markets.vault777.com/api/trades/buy"
SELL_URL = "https://markets.vault777.com/api/trades/sell"
USER_URL = "https://markets.vault777.com/api/me"
POSITIONS_URL = "https://markets.vault777.com/api/me/positions?filter=active"
REDEEM_URL = "https://markets.vault777.com/api/me/redeem"
BTC_PRICE_URL = "https://markets.vault777.com/api/crypto/price?provider=BINANCE&id=BTCUSDT"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://markets.vault777.com/",
    "Origin": "https://markets.vault777.com",
    "Content-Type": "application/json"
}

# Global session — initialized inside main() via init_session(), NOT at module load time.
# This is critical: creating it at module level causes unauthenticated requests to fire
# immediately on import, triggering Vercel's security checkpoint (429).
session = None


def get_proxies():
    """Return proxy dict, or empty dict if disabled."""
    if not USE_PROXY:
        return {}
    proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
    return {"http": proxy_url, "https": proxy_url}


def init_session():
    """Create and configure the global requests session.
    Must be called from main() AFTER .env is loaded — never at module level."""
    global session
    session = requests.Session()
    session.headers.update(HEADERS)
    proxies = get_proxies()
    if proxies:
        session.proxies = proxies
    adapter = HTTPAdapter(
        pool_connections=30,
        pool_maxsize=60,
        max_retries=Retry(total=1, backoff_factor=0.01)
    )
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    # Pre-warm is safe here because it runs AFTER cookies are set and inside main()
    try:
        session.head("https://markets.vault777.com", timeout=2)
        session.get(BTC_PRICE_URL, timeout=1)
    except:
        pass


def rotate_ip():
    """Recreate the session to reset connection state."""
    global session
    if not USE_PROXY:
        print("   [Proxy disabled] Skipping IP rotation.")
        return "skipped"
    session = requests.Session()
    session.headers.update(HEADERS)
    session.proxies = get_proxies()
    adapter = HTTPAdapter(
        pool_connections=30,
        pool_maxsize=60,
        max_retries=Retry(total=1, backoff_factor=0.01)
    )
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    print("   [IP Rotated] Session recreated, waiting 3 seconds...")
    time.sleep(3)
    return "rotated"


def parse_cookie_string(cookie_string):
    cookies = {}
    for cookie in cookie_string.split(';'):
        cookie = cookie.strip()
        if '=' in cookie:
            key, value = cookie.split('=', 1)
            cookies[key.strip()] = unquote(value.strip())
    return cookies


def get_user_info(cookies):
    try:
        response = session.get(USER_URL, cookies=cookies, timeout=3)
        if response.status_code == 200:
            data = response.json()
            if not isinstance(data, dict):
                print(f"DEBUG: Unexpected /me response type: {type(data)}")
                return None
            return data
        print(f"DEBUG: Login failed. Status: {response.status_code} | {response.text[:200]}")
        return None
    except Exception as e:
        print(f"DEBUG: Login exception: {e}")
        return None


def get_btc_price():
    try:
        response = session.get(BTC_PRICE_URL, timeout=1.2)
        if response.status_code == 200:
            return float(response.json().get('price', 0))
        return None
    except:
        return None


def get_latest_market():
    try:
        response = session.get(LATEST_MARKET_URL, timeout=1)
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None


def fetch_market_by_slug(event_slug):
    if not event_slug:
        return None
    try:
        response = session.get(f"{BASE_MARKET_URL}{event_slug}", timeout=1)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return None


def get_opening_price(market_data):
    try:
        if 'event' in market_data and 'markets' in market_data['event']:
            for m in market_data['event']['markets']:
                if 'openingPrice' in m:
                    return float(m['openingPrice'])
        if 'market' in market_data and 'markets' in market_data['market']:
            for m in market_data['market']['markets']:
                if 'openingPrice' in m:
                    return float(m['openingPrice'])
        if 'openingPrice' in market_data:
            return float(market_data['openingPrice'])
    except:
        pass
    return None


def buy_shares(cookies, market_id, amount, outcome_index, max_slippage=0.25):
    payload = {
        "amount": amount,
        "marketId": market_id,
        "maxSlippage": max_slippage,
        "outcomeIndex": outcome_index
    }
    try:
        response = session.post(BUY_URL, cookies=cookies, json=payload, timeout=2)
        if response.status_code == 200:
            return response.json()
        else:
            err_body = ""
            actual_impact = None
            try:
                err_body = response.text[:300]
                match = re.search(r'Price impact ([\d.]+)%', err_body)
                if match:
                    actual_impact = float(match.group(1))
            except:
                pass
            print(f"❌ Buy failed: {response.status_code} | ${amount:,} | slippage={max_slippage} | {err_body}")
            return {"_failed": True, "_status": response.status_code, "_impact": actual_impact}
    except Exception as e:
        print(f"❌ Buy error: {e}")
        return None


def _round_down(amount):
    return int(amount // ROUND_DOWN_TO) * ROUND_DOWN_TO


def _probe_impact(cookies, market_id, amount, outcome_index):
    """Probe with 0.1% slippage to get actual price impact without really buying."""
    payload = {
        "amount": amount,
        "marketId": market_id,
        "maxSlippage": 0.001,
        "outcomeIndex": outcome_index
    }
    try:
        response = session.post(BUY_URL, cookies=cookies, json=payload, timeout=2)
        if response.status_code == 200:
            return 0.0, response.json()
        match = re.search(r'Price impact ([\d.]+)%', response.text[:300])
        if match:
            return float(match.group(1)), None
    except:
        pass
    return None, None


def buy_max_shares(cookies, market_id, outcome_index, max_cap=None):
    """Probe-first buy: finds safe amount within slippage limit, then buys."""
    user = get_user_info(cookies)
    current_balance = user.get('balance', 0) if user else 0

    if current_balance < MIN_BALANCE:
        print(f"⚠️ Balance too low to bet: ${current_balance}")
        return None

    probe_amount = max_cap or _round_down(current_balance * BALANCE_USAGE_PERCENT)
    if probe_amount < ROUND_DOWN_TO:
        print(f"⚠️ Amount too small to probe: ${probe_amount}")
        return None

    print(f"🔍 Probing ${probe_amount:,}...")
    impact, probe_result = _probe_impact(cookies, market_id, probe_amount, outcome_index)

    if probe_result:
        print(f"✅ Bought ${probe_amount:,}! (impact < 0.1%)")
        return probe_result

    amount = probe_amount
    if impact:
        max_allowed = DYNAMIC_SLIPPAGE * 100
        if impact <= max_allowed:
            amount = _round_down(probe_amount)
            print(f"🧮 Impact {impact}% <= {max_allowed}% -> buying full ${amount:,}")
        else:
            smart = probe_amount * (max_allowed / impact) * 0.95
            amount = _round_down(smart)
            print(f"🧮 Impact {impact}% for ${probe_amount:,} -> max at {max_allowed}% = ${amount:,}")
    else:
        amount = _round_down(probe_amount)

    bal_max = _round_down(current_balance * BALANCE_USAGE_PERCENT)
    if bal_max > 0 and amount > bal_max:
        amount = bal_max
    if max_cap and amount > max_cap:
        amount = _round_down(max_cap)
    if amount < ROUND_DOWN_TO:
        print(f"❌ Amount too small")
        return None

    for attempt in range(MAX_BUY_RETRIES):
        print(f"💰 Buying ${amount:,} (attempt {attempt+1})...")
        result = buy_shares(cookies, market_id, amount, outcome_index, DYNAMIC_SLIPPAGE)

        if result and not result.get('_failed'):
            print(f"✅ Bought ${amount:,}!")
            return result

        if result and result.get('_impact'):
            actual_impact = result['_impact']
            max_allowed = DYNAMIC_SLIPPAGE * 100
            smart = amount * (max_allowed / actual_impact) * 0.95
            amount = _round_down(smart)
            print(f"🧮 Recalc: impact {actual_impact}% -> ${amount:,}")
        else:
            amount = _round_down(amount * BUY_RETRY_SHRINK)

        if amount < ROUND_DOWN_TO:
            print(f"❌ Amount too small after retries")
            return None

    print(f"❌ All {MAX_BUY_RETRIES} buy attempts failed")
    return None


def redeem_winnings(cookies):
    try:
        response = session.post(REDEEM_URL, cookies=cookies, timeout=2)
        if response.status_code == 200:
            print(f"   Redeemed winnings!")
            return True
    except:
        pass
    return None


def get_active_positions(cookies):
    try:
        response = session.get(POSITIONS_URL, cookies=cookies, timeout=2)
        if response.status_code == 200:
            return response.json()
    except:
        pass
    return []


def sell_shares(cookies, market_id, outcome_index, shares):
    payload = {"marketId": market_id, "outcomeIndex": outcome_index, "shares": shares}
    for attempt in range(3):
        try:
            response = session.post(SELL_URL, cookies=cookies, json=payload, timeout=3)
            if response.status_code == 200:
                return response.json()
        except:
            pass
        if attempt < 2:
            time.sleep(0.3)
    return None


def sell_all_positions_for_market(cookies, market_id):
    positions = get_active_positions(cookies)
    sold_any = False
    for pos in positions:
        if pos['market']['id'] == market_id:
            for oi in [0, 1]:
                shares = pos.get(f'shares{oi}', 0)
                if shares > 0:
                    if sell_shares(cookies, market_id, oi, shares):
                        sold_any = True
    return sold_any


def get_time_remaining(close_time_str):
    try:
        close_time = datetime.fromisoformat(close_time_str.replace('Z', '+00:00'))
        return max(0, (close_time - datetime.now(timezone.utc)).total_seconds())
    except:
        return -1


def format_duration(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"


def run_active_session(cookies, target_markets):
    markets_completed = 0
    bets_placed = 0
    already_bet_markets = set()

    print(f"\n{'='*60}")
    print(f"5-MINUTE BTC SESSION STARTED")
    print(f"   Target: {target_markets} markets")
    print(f"   Bet amounts: {MULTI_BET_AMOUNTS}")
    print(f"{'='*60}")

    next_redeem = random.randint(3, 5)
    next_ip_rotate = random.randint(10, 12)

    while markets_completed < target_markets:
        latest = get_latest_market()
        if not latest:
            time.sleep(1)
            continue

        market_id = latest.get('marketId', '')
        event_slug = latest.get('eventSlug', '')
        close_time = latest.get('closesAt', '')
        status = latest.get('status')

        if status != 'OPEN':
            time.sleep(2)
            continue

        time_remaining = get_time_remaining(close_time)

        if market_id in already_bet_markets:
            time.sleep(1)
            continue

        if time_remaining < 0:
            time.sleep(1)
            continue

        market_data = fetch_market_by_slug(event_slug)
        opening_price = get_opening_price(market_data) if market_data else None

        if not opening_price:
            time.sleep(1)
            continue

        current_btc = get_btc_price()
        if current_btc:
            direction = "UP" if current_btc >= opening_price else "DOWN"
            print(f"\r   {event_slug} | {time_remaining:.0f}s | Open: {opening_price:.2f} | Now: {current_btc:.2f} {direction}", end="", flush=True)

        if time_remaining <= BET_TIMING_SECONDS and time_remaining > 5:
            print()
            current_price = get_btc_price()
            if not current_price:
                already_bet_markets.add(market_id)
                continue

            if current_price >= opening_price:
                outcome_index = 0
                outcome_name = "OVER"
            else:
                outcome_index = 1
                outcome_name = "UNDER"

            print(f"\n   BTC PRICE ANALYSIS:")
            print(f"      Opening: {opening_price:.2f} | Current: {current_price:.2f}")
            print(f"      -> Betting {outcome_name}")

            # Place first bet
            result = buy_max_shares(cookies, market_id, outcome_index, max_cap=MULTI_BET_AMOUNTS[0])

            if result:
                bets_placed += 1
                stacked_bets = 1
                stop_loss_triggered = False
                max_buys = len(MULTI_BET_AMOUNTS)

                # Stack additional bets
                while stacked_bets < max_buys and not stop_loss_triggered:
                    print(f"   ⏳ Waiting {MULTI_BET_DELAY}s for buy #{stacked_bets+1}/{max_buys}...")

                    delay_elapsed = 0
                    while delay_elapsed < MULTI_BET_DELAY:
                        latest_chk = get_latest_market()
                        if not latest_chk or latest_chk.get('marketId') != market_id:
                            stop_loss_triggered = True
                            break
                        if get_time_remaining(latest_chk.get('closesAt', '')) <= 3:
                            break
                        cur_p = get_btc_price()
                        if cur_p:
                            if (outcome_index == 0 and cur_p < opening_price) or \
                               (outcome_index == 1 and cur_p >= opening_price):
                                print(f"\n   🔴 STOP-LOSS! Price moved against bet! Selling all...")
                                sell_all_positions_for_market(cookies, market_id)
                                stop_loss_triggered = True
                                break
                        time.sleep(POLL_INTERVAL)
                        delay_elapsed += POLL_INTERVAL

                    if stop_loss_triggered:
                        break

                    latest_chk = get_latest_market()
                    if not latest_chk or get_time_remaining(latest_chk.get('closesAt', '')) <= 3:
                        print(f"   ⏱️ Not enough time for more buys.")
                        break

                    cap = MULTI_BET_AMOUNTS[stacked_bets]
                    stack_result = buy_max_shares(cookies, market_id, outcome_index, max_cap=cap)
                    if stack_result:
                        bets_placed += 1
                        stacked_bets += 1
                    else:
                        break

                print(f"   📊 Placed {stacked_bets}/{max_buys} buys")

                # Monitor until close
                if not stop_loss_triggered:
                    print(f"   🔍 Monitoring until close...")
                    while True:
                        latest = get_latest_market()
                        if not latest or latest.get('marketId') != market_id:
                            break
                        if get_time_remaining(latest.get('closesAt', '')) <= 2:
                            print(f"   🏁 Market closing.")
                            break
                        cur_p = get_btc_price()
                        if cur_p:
                            if (outcome_index == 0 and cur_p < opening_price) or \
                               (outcome_index == 1 and cur_p >= opening_price):
                                print(f"\n   🔴 STOP-LOSS! Selling all...")
                                sell_all_positions_for_market(cookies, market_id)
                                break
                        time.sleep(POLL_INTERVAL)
            else:
                print(f"❌ First bet failed.")

            # Periodic tasks
            if markets_completed % 2 == 0:
                user = get_user_info(cookies)
                if user:
                    balance = user.get('balance', 0)
                    print(f"   Balance: ${balance:,.2f}")
                    if balance < MIN_BALANCE:
                        return -1

            if markets_completed % next_redeem == 0 and markets_completed > 0:
                redeem_winnings(cookies)
                next_redeem = random.randint(3, 4)

            if markets_completed % next_ip_rotate == 0 and markets_completed > 0:
                rotate_ip()
                next_ip_rotate = random.randint(10, 12)

            markets_completed += 1
            already_bet_markets.add(market_id)
            print(f"   Markets: {markets_completed}/{target_markets}")
            time.sleep(1)

        elif time_remaining <= 5:
            already_bet_markets.add(market_id)
            time.sleep(2)
        else:
            time.sleep(POLL_INTERVAL)

    print(f"\n{'='*60}")
    print(f"SESSION COMPLETE: {markets_completed} markets | {bets_placed} bets")
    print(f"{'='*60}")
    return markets_completed


def run_inactive_period():
    inactive_seconds = random.uniform(MIN_INACTIVE_HOURS * 3600, MAX_INACTIVE_HOURS * 3600)
    print(f"\n{'='*60}")
    print(f"INACTIVE MODE")
    print(f"   Duration: {format_duration(inactive_seconds)}")
    print(f"{'='*60}")
    time.sleep(inactive_seconds)
    print(f"\nWaking up!")


def main():
    print("\n" + "="*60)
    print("VAULT777 5-MINUTE BTC BOT")
    print("="*60)

    cookies = parse_cookie_string(COOKIE_STRING)

    # ── KEY FIX: init session here, NOT at module load time ──
    # Previously the session (and warm-up requests) were created at module level,
    # meaning unauthenticated requests fired instantly on script start before
    # cookies or delays — triggering Vercel's 429 checkpoint.
    # Now it mirrors multi-bet.py's class-based init pattern.
    print(f"[Proxy] {'ENABLED — ' + PROXY_HOST + ':' + str(PROXY_PORT) if USE_PROXY else 'DISABLED — connecting directly'}")
    init_session()

    user = None
    max_login_retries = 5

    for attempt in range(max_login_retries):
        user = get_user_info(cookies)
        if user:
            break
        print(f"[!] Login failed (Attempt {attempt+1}/{max_login_retries}). Waiting...")
        wait_time = 60 + (attempt * 30)  # 60, 90, 120, 150, 180 seconds
        print(f"[!] Waiting {wait_time} seconds...")
        time.sleep(wait_time)

    if user:
        print(f"✅ Logged in: {user.get('name', 'Unknown')}")
        print(f"   Balance: ${user.get('balance', 0):,.2f}")
    else:
        print("❌ Failed to login after multiple attempts!")
        return

    btc_price = get_btc_price()
    if btc_price:
        print(f"   BTC: ${btc_price:,.2f}")

    print(f"\nStrategy: Compare BTC vs opening at {BET_TIMING_SECONDS}s")
    print(f"Bet amounts: {MULTI_BET_AMOUNTS}")
    print(f"Markets/session: {MIN_MARKETS_PER_SESSION}-{MAX_MARKETS_PER_SESSION}")

    session_count = 0
    total_markets = 0

    while True:
        session_count += 1
        target_markets = random.randint(MIN_MARKETS_PER_SESSION, MAX_MARKETS_PER_SESSION)

        print(f"\n{'#'*60}")
        print(f"  SESSION #{session_count} | Target: {target_markets} | Total: {total_markets}")
        print(f"{'#'*60}")

        markets = run_active_session(cookies, target_markets)

        if markets == -1:
            print(f"\nBOT STOPPED - Low balance")
            break

        total_markets += markets

        user = get_user_info(cookies)
        if user:
            print(f"\n   Balance: ${user.get('balance', 0):,.2f}")

        run_inactive_period()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nBot stopped!")
