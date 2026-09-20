from datetime import datetime, timezone

from intelligence.news.models import NewsItem, SentimentLabel
from intelligence.news.sentiment import FallbackSentimentModel, LexiconSentimentModel, PhoBERTSentimentModel


def item(text="ACB lợi nhuận tăng mạnh"):
    return NewsItem("1", "test", "https://example.test/1", datetime.now(timezone.utc), text)


def test_phobert_probabilities_and_load_once():
    loads = []
    class FakePipeline:
        def __call__(self, *args, **kwargs):
            return [[{"label":"LABEL_0","score":.1},{"label":"LABEL_1","score":.2},{"label":"LABEL_2","score":.7}]]
    model = PhoBERTSentimentModel("test", loader=lambda: loads.append(1) or FakePipeline())
    first, second = model.analyze(item()), model.analyze(item())
    assert first.label == SentimentLabel.POSITIVE
    assert abs(first.probability_positive + first.probability_neutral + first.probability_negative - 1) < 1e-6
    assert first.model_confidence == .7 and len(loads) == 1
    assert second.backend == "phobert"


def test_explicit_lexicon_fallback():
    class Broken:
        def analyze(self, value):
            raise RuntimeError("offline")
    result = FallbackSentimentModel(Broken(), LexiconSentimentModel(backend="lexicon_fallback")).analyze(item())
    assert result.backend == "lexicon_fallback"
    assert result.label == SentimentLabel.POSITIVE
