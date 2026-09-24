from datetime import datetime, timezone

from intelligence.news.models import NewsItem, SentimentLabel, SentimentResult
from intelligence.news.sentiment import (
    FINANCIAL_CALIBRATION_VERSION,
    FallbackSentimentModel,
    FinancialHeadlineCalibrationModel,
    LexiconSentimentModel,
    PhoBERTSentimentModel,
)


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


def test_phobert_accepts_direct_single_input_pipeline_shape():
    class DirectPipeline:
        def __call__(self, *args, **kwargs):
            return [{"label":"LABEL_0","score":.1},
                    {"label":"LABEL_1","score":.2},
                    {"label":"LABEL_2","score":.7}]
    result = PhoBERTSentimentModel("test", loader=DirectPipeline).analyze(item())
    assert result.label == SentimentLabel.POSITIVE
    assert result.probability_positive == .7


def test_financial_calibration_corrects_clear_direction_but_preserves_ambiguity():
    class ContrarianModel:
        def analyze(self, value):
            return SentimentResult(
                SentimentLabel.NEGATIVE, .05, .15, .80, .80,
                "test", "contrarian", "1", datetime.now(timezone.utc),
            )

    model = FinancialHeadlineCalibrationModel(ContrarianModel())
    positive = model.analyze(item("FPT lãi ròng gần 30 tỷ đồng mỗi ngày trong tháng 8"))
    assert positive.label == SentimentLabel.POSITIVE
    assert positive.score >= .1999
    assert positive.calibration_version == FINANCIAL_CALIBRATION_VERSION
    assert positive.model_confidence < .80

    negative = model.analyze(item("LNST giảm so với cùng kỳ"))
    assert negative.label == SentimentLabel.NEGATIVE
    assert negative.calibration_version == FINANCIAL_CALIBRATION_VERSION

    ambiguous = model.analyze(item("Doanh thu tăng nhưng lợi nhuận giảm"))
    assert ambiguous.label == SentimentLabel.NEGATIVE
    assert ambiguous.probability_negative == .80
    assert ambiguous.calibration_version is None

    negated = model.analyze(item("Lợi nhuận không tăng so với cùng kỳ"))
    assert negated.probability_negative == .80
    assert negated.calibration_version is None
