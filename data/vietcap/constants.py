"""Constants for the unofficial Vietcap market-data interface."""

DEFAULT_SOCKET_URL = "https://trading.vietcap.com.vn"
DEFAULT_SOCKET_PATH = "/ws/price/socket.io"
DEFAULT_CONNECT_TIMEOUT_SECONDS = 20.0
SOCKET_TRANSPORTS = ("websocket",)
MATCH_PRICE_EVENT = "w-match-price"
INDEX_EVENT = "index"
VNINDEX_SYMBOL = "VNINDEX"