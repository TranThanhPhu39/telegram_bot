"""Contract tests for the vendored Vietcap protobuf schema."""

from data.vietcap.proto import price_pb2


def test_proto_package_and_required_messages_exist() -> None:
    assert price_pb2.DESCRIPTOR.package == "pricePackage"
    assert price_pb2.MatchPriceMessage.DESCRIPTOR.full_name == (
        "pricePackage.MatchPriceMessage"
    )
    assert price_pb2.BidAskMessage.DESCRIPTOR.full_name == (
        "pricePackage.BidAskMessage"
    )
    assert price_pb2.IndexMessage.DESCRIPTOR.full_name == "pricePackage.IndexMessage"


def test_match_price_message_round_trip() -> None:
    source = price_pb2.MatchPriceMessage(
        type="MATCH_PRICE",
        code="FPT",
        symbol="FPT",
        matchPrice=103.2,
        matchVol=1_500,
        accumulatedVolume=2_345_600,
        time="11:05:21",
        isMatchPrice=True,
    )

    decoded = price_pb2.MatchPriceMessage.FromString(source.SerializeToString())

    assert decoded == source
    assert decoded.symbol == "FPT"
    assert decoded.matchPrice == 103.2


def test_bid_ask_message_round_trip() -> None:
    source = price_pb2.BidAskMessage(
        type="BID_ASK",
        code="ACB",
        symbol="ACB",
        bidPrices=[price_pb2.BidAskPrice(price=25.35, volume=10_000)],
        askPrices=[price_pb2.BidAskPrice(price=25.4, volume=12_000)],
        session="CONTINUOUS",
        bidCount=3,
        askCount=3,
    )

    decoded = price_pb2.BidAskMessage.FromString(source.SerializeToString())

    assert decoded == source
    assert decoded.bidPrices[0].price == 25.35
    assert decoded.askPrices[0].volume == 12_000


def test_index_message_round_trip() -> None:
    source = price_pb2.IndexMessage(
        code="VNINDEX",
        symbol="VNINDEX",
        price=1_280.5,
        change=5.25,
        changePercent=0.41,
        totalShares=500_000_000,
        totalValue=12_500_000_000_000,
        totalStockIncrease=250,
        totalStockDecline=120,
        totalStockNoChange=60,
        time="11:05:22",
    )

    decoded = price_pb2.IndexMessage.FromString(source.SerializeToString())

    assert decoded == source
    assert decoded.symbol == "VNINDEX"
    assert decoded.totalStockIncrease == 250
