import requests
import json
import time
import hmac
import hashlib
from typing import Dict, List, Optional, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DeribitClient:
    """Client for interacting with Deribit API (REST and WebSocket)"""

    def __init__(self, api_key: str, api_secret: str, env: str = "test"):
        """
        Initialize Deribit client

        Args:
            api_key: API key
            api_secret: API secret
            env: 'test' for testnet, 'prod' for production
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.env = env

        if env == "test":
            self.base_url = "https://test.deribit.com/api/v2"
        else:
            self.base_url = "https://www.deribit.com/api/v2"

        self.access_token = None
        self.refresh_token = None
        self.token_expiry = 0

    def authenticate(self) -> bool:
        """
        Authenticate with Deribit API

        Returns:
            bool: True if authentication successful
        """
        try:
            endpoint = "/public/auth"
            params = {
                "grant_type": "client_credentials",
                "client_id": self.api_key,
                "client_secret": self.api_secret
            }

            response = self._request("GET", endpoint, params)

            if response and "result" in response:
                self.access_token = response["result"]["access_token"]
                self.refresh_token = response["result"]["refresh_token"]
                self.token_expiry = time.time() + response["result"]["expires_in"]
                logger.info("Successfully authenticated with Deribit")
                return True
            else:
                logger.error(f"Authentication failed: {response}")
                return False

        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    def _check_token(self):
        """Check if token is valid and refresh if needed"""
        if not self.access_token or time.time() >= self.token_expiry - 60:
            logger.info("Token expired or missing, re-authenticating...")
            self.authenticate()

    def _request(self, method: str, endpoint: str, params: Dict = None, private: bool = False,
                 max_retries: int = 3, timeout: int = 30) -> Optional[Dict]:
        """
        Make HTTP request to Deribit API with retry logic

        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint
            params: Request parameters
            private: Whether this is a private endpoint requiring auth
            max_retries: Maximum number of retry attempts
            timeout: Request timeout in seconds

        Returns:
            API response as dict
        """
        if private:
            self._check_token()

        url = f"{self.base_url}{endpoint}"
        
        # DEBUG PRINT
        if endpoint == "/private/get_account_summary":
            print(f"DEBUG REQ: {endpoint} Params: {params}")
            
        headers = {}

        if private and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        last_exception = None

        for attempt in range(max_retries):
            try:
                if method == "GET":
                    response = requests.get(url, params=params, headers=headers, timeout=timeout)
                elif method == "POST":
                    response = requests.post(url, json=params, headers=headers, timeout=timeout)
                else:
                    raise ValueError(f"Unsupported method: {method}")

                response.raise_for_status()
                json_resp = response.json()
                
                if "error" in json_resp:
                    logger.error(f"Deribit API Error {endpoint}: {json_resp['error']}")
                    
                return json_resp

            except requests.exceptions.Timeout as e:
                last_exception = e
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.warning(f"Timeout on {endpoint} (attempt {attempt + 1}/{max_retries}), retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Request timeout for {endpoint} after {max_retries} attempts: {e}")
                    return None

            except requests.exceptions.RequestException as e:
                last_exception = e
                # Check for API Error Response (e.g. 400 Bad Request with JSON)
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        # Attempt to parse JSON error from response
                        error_json = e.response.json()
                        if "error" in error_json:
                            logger.error(f"API Error {endpoint}: {error_json['error']}")
                            return error_json
                    except ValueError:
                        # Not JSON
                        pass
                        
                    logger.error(f"Request error for {endpoint}: {e} -> {e.response.text}")
                else:
                    logger.error(f"Request error for {endpoint}: {e}")
                return None

        return None

    # Public endpoints

    def get_index_price(self, currency: str) -> Optional[float]:
        """Get current index price for currency (BTC or ETH)"""
        endpoint = "/public/get_index_price"
        params = {"index_name": f"{currency.lower()}_usd"}
        response = self._request("GET", endpoint, params)

        if response and "result" in response:
            return response["result"]["index_price"]
        return None

    def get_ticker(self, instrument_name: str) -> Optional[Dict]:
        """Get ticker for instrument"""
        endpoint = "/public/ticker"
        params = {"instrument_name": instrument_name}
        response = self._request("GET", endpoint, params)

        if response and "result" in response:
            return response["result"]
        return None

    def get_instruments(self, currency: str, kind: str = "option", expired: bool = False) -> List[Dict]:
        """
        Get available instruments

        Args:
            currency: BTC or ETH
            kind: option, future, spot
            expired: Include expired instruments
        """
        endpoint = "/public/get_instruments"
        params = {
            "currency": currency.upper(),
            "kind": kind,
            "expired": "true" if expired else "false"
        }
        response = self._request("GET", endpoint, params)

        if response and "result" in response:
            return response["result"]
        return []

    def get_order_book(self, instrument_name: str, depth: int = 5) -> Optional[Dict]:
        """Get order book for instrument"""
        endpoint = "/public/get_order_book"
        params = {
            "instrument_name": instrument_name,
            "depth": depth
        }
        response = self._request("GET", endpoint, params)

        if response and "result" in response:
            return response["result"]
        return None

    def get_historical_volatility(self, currency: str) -> Optional[List[Dict]]:
        """Get historical volatility data"""
        endpoint = "/public/get_historical_volatility"
        params = {"currency": currency.upper()}
        response = self._request("GET", endpoint, params)

        if response and "result" in response:
            return response["result"]
        return None

    def get_ohlcv(self, instrument_name: str, timeframe: str = "15", limit: int = 50) -> List[List[float]]:
        """
        Get OHLCV data (TradingView chart data)
        
        Args:
            instrument_name: e.g., BTC-PERPETUAL
            timeframe: Resolution in minutes (1, 3, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1D)
            limit: Number of candles to return
            
        Returns:
            List of [timestamp, open, high, low, close, volume]
        """
        endpoint = "/public/get_tradingview_chart_data"
        
        # Calculate start/end timestamps
        # Resolution is in minutes (except 1D)
        if timeframe == "1D":
            res_minutes = 1440
        elif timeframe.endswith("m"):
             res_minutes = int(timeframe[:-1])
        else:
             res_minutes = int(timeframe)
             
        end_ts = int(time.time() * 1000)
        start_ts = end_ts - (limit * res_minutes * 60 * 1000)
        
        params = {
            "instrument_name": instrument_name,
            "start_timestamp": start_ts,
            "end_timestamp": end_ts,
            "resolution": timeframe.replace("m", "") # Deribit uses "15" not "15m"
        }
        
        response = self._request("GET", endpoint, params)
        
        if response and "result" in response:
            result = response["result"]
            # Format: ticks (timestamp), open, high, low, close, volume
            # We want list of lists: [[ts, o, h, l, c, v], ...]
            ticks = result.get("ticks", [])
            opens = result.get("open", [])
            highs = result.get("high", [])
            lows = result.get("low", [])
            closes = result.get("close", [])
            volumes = result.get("volume", [])
            
            ohlcv = []
            for i in range(len(ticks)):
                ohlcv.append([
                    ticks[i],
                    opens[i],
                    highs[i],
                    lows[i],
                    closes[i],
                    volumes[i]
                ])
            return ohlcv
            
        return []

    # Private endpoints

    def get_account_summary(self, currency: str) -> Optional[Dict]:
        """Get account summary including balance and equity"""
        endpoint = "/private/get_account_summary"
        params = {"currency": currency.upper()}
        response = self._request("GET", endpoint, params, private=True)

        if response and "result" in response:
            return response["result"]
        return None

    def get_positions(self, currency: str, kind: str = "option") -> List[Dict]:
        """Get open positions"""
        endpoint = "/private/get_positions"
        params = {
            "currency": currency.upper(),
            "kind": kind
        }
        response = self._request("GET", endpoint, params, private=True)

        if response and "result" in response:
            return response["result"]
        return []

    def buy(self, instrument_name: str, amount: float, price: Optional[float] = None,
            label: str = "", post_only: bool = False, **kwargs) -> Optional[Dict]:
        """
        Place buy order

        Args:
            instrument_name: Instrument name
            amount: Amount in contracts
            price: Limit price (None for market order)
            label: Order label for tracking
            post_only: Post-only order
            **kwargs: Additional parameters (type, trigger, reduce_only, etc.)
        """
        endpoint = "/private/buy"
        params = {
            "instrument_name": instrument_name,
            "amount": amount,
            "type": "limit" if price else "market"
        }

        if price is not None:
             params["price"] = price
        if label:
            params["label"] = label
        if post_only:
            params["post_only"] = "true"
            
        # Merge additional kwargs (overriding defaults if necessary)
        if kwargs:
            for k, v in kwargs.items():
                if k == "reduce_only" and isinstance(v, bool):
                     params[k] = "true" if v else "false"
                else:
                     if v is not None:
                        params[k] = v

        response = self._request("GET", endpoint, params, private=True)

        if response:
            if "result" in response:
                return response["result"]["order"]
            if "error" in response:
                return response
        return None

    def sell(self, instrument_name: str, amount: float, price: Optional[float] = None,
             label: str = "", post_only: bool = False, **kwargs) -> Optional[Dict]:
        """
        Place sell order

        Args:
            instrument_name: Instrument name
            amount: Amount in contracts
            price: Limit price (None for market order)
            label: Order label for tracking
            post_only: Post-only order
            **kwargs: Additional parameters (type, trigger, reduce_only, etc.)
        """
        endpoint = "/private/sell"
        params = {
            "instrument_name": instrument_name,
            "amount": amount,
            "type": "limit" if price else "market"
        }

        if price is not None:
             params["price"] = price
        if label:
            params["label"] = label
        if post_only:
            params["post_only"] = "true"
            
        # Merge additional kwargs
        if kwargs:
            for k, v in kwargs.items():
                if k == "reduce_only" and isinstance(v, bool):
                     params[k] = "true" if v else "false"
                else:
                     if v is not None:
                        params[k] = v

        response = self._request("GET", endpoint, params, private=True)

        if response:
            if "result" in response:
                return response["result"]["order"]
            if "error" in response:
                return response
        return None

    def edit(self, order_id: str, amount: float, price: Optional[float] = None,
             post_only: bool = False, **kwargs) -> Optional[Dict]:
        """
        Edit an open order
        
        Args:
            order_id: Order ID to edit
            amount: New amount
            price: New price (optional)
            post_only: Post-only order
            **kwargs: Additional parameters (trigger_price, etc.)
        """
        endpoint = "/private/edit"
        params = {
            "order_id": order_id,
            "amount": amount
        }
        
        if price is not None:
             params["price"] = price
             
        if post_only:
            params["post_only"] = "true"
            
        # Merge additional kwargs
        if kwargs:
            for k, v in kwargs.items():
                if k == "reduce_only" and isinstance(v, bool):
                     params[k] = "true" if v else "false"
                else:
                     params[k] = v
            
        response = self._request("GET", endpoint, params, private=True)
        
        if response:
            if "result" in response:
                return response["result"]["order"]
            if "error" in response:
                return response
        return None

    def get_order_state(self, order_id: str) -> Optional[Dict]:
        """
        Get order state by order ID

        Args:
            order_id: Order ID to check

        Returns:
            Order state dict or None
        """
        endpoint = "/private/get_order_state"
        params = {"order_id": order_id}
        response = self._request("GET", endpoint, params, private=True)

        if response and "result" in response:
            return response["result"]
        return None

    def close_position(self, instrument_name: str, type_: str = "market") -> Optional[Dict]:
        """Close position for instrument"""
        endpoint = "/private/close_position"
        params = {
            "instrument_name": instrument_name,
            "type": type_
        }
        response = self._request("GET", endpoint, params, private=True)

        if response and "result" in response:
            return response["result"]
        return None

    def cancel(self, order_id: str) -> bool:
        """
        Cancel a single order by order ID.

        Args:
            order_id: The order ID to cancel

        Returns:
            True if successfully cancelled (or already gone), False on API error
        """
        endpoint = "/private/cancel"
        params = {"order_id": order_id}
        response = self._request("GET", endpoint, params, private=True)

        if response and "result" in response:
            state = response["result"].get("order_state", "")
            logger.info(f"Cancelled order {order_id} → state: {state}")
            return True

        if response and "error" in response:
            err = response["error"]
            code = err.get("code", 0)
            # 10004 = order not found (already filled/cancelled) — treat as success
            if code == 10004:
                logger.info(f"Order {order_id} already gone (code 10004) — orphan cleanup OK")
                return True
            logger.error(f"Failed to cancel order {order_id}: {err}")
            return False

        logger.error(f"Failed to cancel order {order_id}: no response")
        return False

    def cancel_all(self) -> bool:
        """Cancel all open orders"""
        endpoint = "/private/cancel_all"
        response = self._request("GET", endpoint, {}, private=True)
        return response is not None

    def get_user_trades_by_instrument(
        self,
        instrument_name: str,
        count: int = 20,
        sorting: str = "desc",
    ) -> List[Dict]:
        """Recent fills for an instrument (newest first when sorting=desc)."""
        endpoint = "/private/get_user_trades_by_instrument"
        params = {
            "instrument_name": instrument_name,
            "count": count,
            "sorting": sorting,
        }
        response = self._request("GET", endpoint, params, private=True)
        if response and "result" in response:
            result = response["result"]
            if isinstance(result, dict):
                return result.get("trades", [])
            if isinstance(result, list):
                return result
        return []

    def get_futures_positions(self, currency: str) -> List[Dict]:
        """
        Get open futures and perpetual positions for a currency.
        On Deribit, perpetuals are classified as 'future' kind.

        Args:
            currency: BTC or ETH

        Returns:
            List of position dicts with keys: instrument_name, size, direction, etc.
        """
        endpoint = "/private/get_positions"
        params = {
            "currency": currency.upper(),
            "kind": "future"
        }
        response = self._request("GET", endpoint, params, private=True)

        if response and "result" in response:
            return response["result"]
        return []

    def get_open_orders(self, currency: str = None, kind: str = "option") -> List[Dict]:
        """Get all open orders"""
        endpoint = "/private/get_open_orders_by_currency" if currency else "/private/get_open_orders"
        params = {}
        if currency:
            params["currency"] = currency.upper()
            params["kind"] = kind

        response = self._request("GET", endpoint, params, private=True)

        if response and "result" in response:
            return response["result"]
        return []

    def get_open_orders_by_instrument(self, instrument_name: str, type: str = None) -> List[Dict]:
        """
        Get open orders for a specific instrument
        
        Args:
            instrument_name: Instrument name
            type: Order type (limit, stop_limit, etc.) or None for all
            
        Returns:
            List of open orders
        """
        endpoint = "/private/get_open_orders_by_instrument"
        params = {"instrument_name": instrument_name}
        if type:
            params["type"] = type
            
        response = self._request("GET", endpoint, params, private=True)

        if response and "result" in response:
            return response["result"]
        return []
