"""
vector_store.py
----------------
A minimal local "vector database" for the Document Agent. Uses scikit-learn's
TF-IDF + cosine similarity instead of an external embedding API, so the whole
system runs offline with no API keys. Swappable later: replace the internals
of this class with a real embedding model/API and every agent that calls
search() keeps working unchanged.

Each research SESSION gets its own index, stored as a pickle file under
data/vector_indexes/session_<id>.pkl.
"""

import os
import pickle
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.paths import INDEX_DIR


class SessionVectorIndex:
    def __init__(self, session_id: int):
        self.session_id = session_id
        # MILESTONE 4 OPTIMIZATION (retrieval quality):
        #   - ngram_range=(1, 2): indexes two-word phrases ("net income",
        #     "going concern", "material weakness") as well as single words,
        #     so a search for "material weakness" scores a chunk containing
        #     that exact phrase much higher than one that just happens to
        #     contain "material" and "weakness" separately.
        #   - sublinear_tf=True: uses 1+log(term frequency) instead of raw
        #     counts, so a chunk repeating one word many times doesn't
        #     drown out chunks that are a better topical match overall.
        #   - min_df=1 (default) is kept deliberately: a research session's
        #     corpus is small (a handful of documents), so even a rare term
        #     that appears in only one chunk is often exactly the one a
        #     query is looking for and should not be filtered out.
        self.vectorizer = TfidfVectorizer(
            stop_words="english", max_features=20000,
            ngram_range=(1, 2), sublinear_tf=True,
        )
        self.matrix = None
        self.chunk_ids = []
        self.texts = []

    @property
    def _path(self):
        os.makedirs(INDEX_DIR, exist_ok=True)
        return os.path.join(INDEX_DIR, f"session_{self.session_id}.pkl")

    def save(self):
        with open(self._path, "wb") as f:
            pickle.dump({"vectorizer": self.vectorizer, "matrix": self.matrix,
                         "chunk_ids": self.chunk_ids, "texts": self.texts}, f)

    @classmethod
    def load(cls, session_id: int):
        inst = cls(session_id)
        if os.path.exists(inst._path):
            with open(inst._path, "rb") as f:
                state = pickle.load(f)
            inst.vectorizer = state["vectorizer"]
            inst.matrix = state["matrix"]
            inst.chunk_ids = state["chunk_ids"]
            inst.texts = state["texts"]
        return inst

    def add_chunks(self, chunk_ids: list, texts: list):
        self.chunk_ids.extend(chunk_ids)
        self.texts.extend(texts)
        self.matrix = self.vectorizer.fit_transform(self.texts)
        self.save()

    def search(self, query: str, top_k: int = 5):
        if self.matrix is None or len(self.texts) == 0:
            return []
        query_vec = self.vectorizer.transform([query])
        sims = cosine_similarity(query_vec, self.matrix)[0]
        top_indices = np.argsort(sims)[::-1][:top_k]
        results = []
        for idx in top_indices:
            if sims[idx] <= 0:
                continue
            results.append((self.chunk_ids[idx], float(sims[idx]), self.texts[idx]))
        return results


def get_index(session_id: int) -> SessionVectorIndex:
    return SessionVectorIndex.load(session_id)
