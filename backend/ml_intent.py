from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
import joblib
import os

MODEL_PATH = "ml_model.pkl"
VECTORIZER_PATH = "vectorizer.pkl"

class IntentClassifier:
    def __init__(self):
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            stop_words="english"
        )
        self.model = LogisticRegression(max_iter=1000)

    def train(self, texts, labels):
        X = self.vectorizer.fit_transform(texts)
        self.model.fit(X, labels)

        joblib.dump(self.model, MODEL_PATH)
        joblib.dump(self.vectorizer, VECTORIZER_PATH)

    def load(self):
        if os.path.exists(MODEL_PATH) and os.path.exists(VECTORIZER_PATH):
            self.model = joblib.load(MODEL_PATH)
            self.vectorizer = joblib.load(VECTORIZER_PATH)
            return True
        return False

    def predict(self, text):
        X = self.vectorizer.transform([text])
        probs = self.model.predict_proba(X)[0]
        idx = probs.argmax()
        return self.model.classes_[idx], probs[idx]
