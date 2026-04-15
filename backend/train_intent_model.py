from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
import joblib

# Training data (you can expand this later)
texts = [
    "Who is the cdean?",
    "Who are the university officials?",
    "Tell me about BSU Lipa history",
    "What announcements are available?",
    "Show latest announcements",
    "Where is the registrar office?",
    "How can I contact the dean?"
]

labels = [
    "authority",
    "authority",
    "history",
    "announcement",
    "announcement",
    "location",
    "authority"
]

vectorizer = TfidfVectorizer(ngram_range=(1,2))
X = vectorizer.fit_transform(texts)

model = LogisticRegression(max_iter=1000)
model.fit(X, labels)

joblib.dump(model, "intent_model.joblib")
joblib.dump(vectorizer, "vectorizer.joblib")

print("✅ Intent model trained and saved")
