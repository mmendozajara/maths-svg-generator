"""Search the image catalogue for existing images matching a description.

Supports two search modes:
  1. CLIP vision search (preferred) — uses pre-computed image embeddings + text query encoding
  2. TF-IDF text search (fallback) — matches against accessibility descriptions

Usage:
    from image_search import ImageCatalogueSearch

    search = ImageCatalogueSearch()  # auto-detects CLIP or TF-IDF
    results = search.find_matches("A number line from 0 to 10 with 3 and 7 marked", top_k=5)
    for r in results:
        print(r["score"], r["description"], r["image_url"])
"""

import json
import math
import re
import time
from collections import Counter
from pathlib import Path

import numpy as np

# Try CLIP model
try:
    from sentence_transformers import SentenceTransformer
    HAS_CLIP = True
except ImportError:
    HAS_CLIP = False

# Try scikit-learn for TF-IDF fallback
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


def _normalise(text: str) -> str:
    """Normalise text for matching: lowercase, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = re.sub(r"ask your teacher for more information\.?", "", text)
    text = re.sub(r"[^\w\s.\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class ImageCatalogueSearch:
    """Searchable index of existing images from the gold standard catalogue."""

    def __init__(
        self,
        catalogue_path: str | Path = None,
        embeddings_path: str | Path = None,
        clip_model: str = "clip-ViT-B-32",
    ):
        base_dir = Path(__file__).resolve().parent

        if catalogue_path is None:
            catalogue_path = base_dir / "image_catalogue.json"
        if embeddings_path is None:
            embeddings_path = base_dir / "clip_embeddings.npz"

        catalogue_path = Path(catalogue_path)
        embeddings_path = Path(embeddings_path)

        if not catalogue_path.exists():
            raise FileNotFoundError(
                f"Image catalogue not found at {catalogue_path}. "
                f"Run: python build_image_catalogue.py"
            )

        with open(catalogue_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.images = data.get("images", [])
        self.total = len(self.images)

        # Build TF-IDF index (always, used standalone or as part of hybrid)
        self._has_tfidf = False
        if HAS_SKLEARN:
            self._init_tfidf()

        # Try CLIP for hybrid (CLIP + TF-IDF), fall back to TF-IDF only
        if HAS_CLIP and embeddings_path.exists() and self._has_tfidf:
            self._init_clip(embeddings_path, clip_model)
            self._method = "hybrid"
        elif HAS_CLIP and embeddings_path.exists():
            self._init_clip(embeddings_path, clip_model)
            self._method = "clip"
        elif self._has_tfidf:
            self._method = "tfidf"
        else:
            self._init_simple()

    def _init_clip(self, embeddings_path: Path, model_name: str):
        """Load CLIP embeddings and model for vision-based search."""
        data = np.load(embeddings_path)
        self._clip_embeddings = data["embeddings"]  # (N, D) normalised
        self._clip_valid_indices = data["valid_indices"]  # maps row -> catalogue index

        # Build reverse mapping: catalogue_index -> clip_row
        self._catalogue_to_clip = {}
        for row, cat_idx in enumerate(self._clip_valid_indices):
            self._catalogue_to_clip[int(cat_idx)] = row

        # Load CLIP model for text encoding
        self._clip_model = SentenceTransformer(model_name)

    def _init_tfidf(self):
        """Build TF-IDF index."""
        descriptions = [_normalise(img["description"]) for img in self.images]
        self._vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            max_features=50000,
            sublinear_tf=True,
            stop_words="english",
        )
        self._tfidf_matrix = self._vectorizer.fit_transform(descriptions)
        self._has_tfidf = True

    def _init_simple(self):
        """Build simple word-overlap index as last resort."""
        self._descriptions = [_normalise(img["description"]) for img in self.images]
        self._word_sets = []
        self._idf = Counter()

        for desc in self._descriptions:
            words = set(desc.split())
            self._word_sets.append(words)
            for w in words:
                self._idf[w] += 1

        n = len(self._descriptions)
        for w in self._idf:
            self._idf[w] = math.log(n / (1 + self._idf[w]))

        self._method = "word_overlap"

    def find_matches(self, query: str, top_k: int = 5, min_score: float = 0.1) -> list[dict]:
        """Find the top-k most similar images to the query description.

        Args:
            query: Natural language description of the desired image.
            top_k: Number of results to return.
            min_score: Minimum similarity score (0-1) to include.

        Returns:
            List of dicts with keys: score, description, image_url, image_path,
            width, height, source_book, book_title, idea_title, image_format.
        """
        if not self.images:
            return []

        if self._method == "hybrid":
            return self._search_hybrid(query, top_k, min_score)
        elif self._method == "clip":
            return self._search_clip(query, top_k, min_score)
        elif self._method == "tfidf":
            return self._search_tfidf(query, top_k, min_score)
        else:
            return self._search_simple(query, top_k, min_score)

    _STOP_WORDS = {
        "a", "an", "the", "of", "in", "on", "is", "it", "to", "and", "or",
        "with", "that", "this", "for", "from", "by", "at", "as", "be", "are",
        "was", "were", "has", "have", "had", "its", "no", "not", "but", "do",
        "does", "did", "can", "could", "will", "would", "should", "may",
        "more", "most", "very", "also", "than", "then", "into", "about",
        "which", "when", "where", "how", "all", "each", "every", "both",
        "few", "some", "any", "other", "new", "old", "your", "their",
        "our", "ask", "teacher", "information", "image", "shows", "showing",
        "shown", "drawn", "labeled", "labelled", "part", "diagram",
    }

    @classmethod
    def _extract_keywords(cls, text: str) -> set[str]:
        """Extract meaningful keywords from normalised text, filtering stop words."""
        return {w for w in text.split() if w not in cls._STOP_WORDS and len(w) > 1}

    @classmethod
    def _keyword_coverage(cls, query_norm: str, desc_norm: str) -> float:
        """Compute what fraction of important query keywords appear in the description.

        Returns a value between 0.0 (no overlap) and 1.0 (all keywords present).
        """
        query_words = cls._extract_keywords(query_norm)
        if not query_words:
            return 1.0
        desc_words = set(desc_norm.split())
        matched = sum(1 for w in query_words if w in desc_words)
        return matched / len(query_words)

    @classmethod
    def _extra_content_penalty(cls, query_norm: str, desc_norm: str) -> float:
        """Penalize when the match description introduces major new concepts not in the query.

        "A scalene triangle" → "A circle O with scalene triangle MNO" is bad because
        "circle" is a major concept absent from the query. But
        "A right triangle" → "A right-angled triangle with sides labelled L, M, N"
        is fine because the extra terms are just details (labels), not new concepts.

        We check: of the description's keywords, what fraction are totally unrelated
        to any query keyword? Single letters (labels like A, B, M, N) and numbers
        are excluded since they're just specifics.
        """
        query_words = cls._extract_keywords(query_norm)
        desc_words = cls._extract_keywords(desc_norm)
        if not desc_words or not query_words:
            return 1.0

        # Ignore single-char labels and pure numbers in description
        desc_content = {w for w in desc_words if len(w) > 1 and not w.replace(".", "").isdigit()}
        if not desc_content:
            return 1.0

        # Count description content words that share no stem overlap with any query word
        def _stems_overlap(w1: str, w2: str) -> bool:
            """Check if two words share a common stem (first 4+ chars)."""
            min_len = min(len(w1), len(w2))
            prefix = min(4, min_len)
            return w1[:prefix] == w2[:prefix]

        extra_concepts = 0
        for dw in desc_content:
            if any(_stems_overlap(dw, qw) for qw in query_words):
                continue
            extra_concepts += 1

        extra_ratio = extra_concepts / len(desc_content)

        # Penalty kicks in when > 30% of description content is unrelated concepts
        # 0-30% extra → 1.0, 50% → 0.85, 75% → 0.66
        if extra_ratio <= 0.3:
            return 1.0
        return max(0.6, 1.0 - 0.75 * (extra_ratio - 0.3))

    def _search_hybrid(self, query: str, top_k: int, min_score: float) -> list[dict]:
        """Search using combined TF-IDF text + CLIP vision similarity.

        Strategy:
          1. Get top-50 candidates from TF-IDF (text relevance filter)
          2. Re-rank candidates using CLIP vision similarity
          3. Final score = 0.4 * tfidf + 0.6 * clip, with keyword coverage penalty
        Keyword coverage ensures that if the query mentions specific terms
        (e.g. "grid", "labelled") that are absent from the match, the score drops.
        """
        # Step 1: TF-IDF candidates (broader pool)
        norm_query = _normalise(query)
        query_vec = self._vectorizer.transform([norm_query])
        tfidf_scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten()

        # Get top-50 by text
        candidate_count = min(50, len(self.images))
        tfidf_top = tfidf_scores.argsort()[-candidate_count:][::-1]

        # Step 2: CLIP scoring for candidates
        query_emb = self._clip_model.encode([query], show_progress_bar=False)
        query_emb = query_emb / np.linalg.norm(query_emb, axis=1, keepdims=True)

        # Step 3: Combined scoring with keyword coverage penalty
        results = []
        for cat_idx in tfidf_top:
            cat_idx = int(cat_idx)
            tfidf_score = float(tfidf_scores[cat_idx])

            # Skip if TF-IDF score is too low (no text relevance at all)
            if tfidf_score < 0.05:
                continue

            # Get CLIP score if available for this image
            clip_row = self._catalogue_to_clip.get(cat_idx)
            if clip_row is not None:
                clip_score = float(self._clip_embeddings[clip_row] @ query_emb.flatten())
            else:
                clip_score = 0.0

            # Keyword penalties
            desc_norm = _normalise(self.images[cat_idx].get("description", ""))
            coverage = self._keyword_coverage(norm_query, desc_norm)
            extra_penalty = self._extra_content_penalty(norm_query, desc_norm)

            # Combined score with both penalties:
            # - coverage: penalize missing query keywords (0.5 + 0.5 * coverage)
            # - extra_penalty: penalize extra description keywords (1.0 to ~0.5)
            combined = (0.4 * tfidf_score + 0.6 * clip_score) * (0.5 + 0.5 * coverage) * extra_penalty

            if combined >= min_score:
                entry = self.images[cat_idx].copy()
                entry["score"] = round(combined, 3)
                results.append(entry)

        # Sort by combined score descending
        results.sort(key=lambda x: -x["score"])
        return results[:top_k]

    def _search_clip(self, query: str, top_k: int, min_score: float) -> list[dict]:
        """Search using CLIP text-to-image similarity."""
        # Encode text query
        query_emb = self._clip_model.encode([query], show_progress_bar=False)
        query_emb = query_emb / np.linalg.norm(query_emb, axis=1, keepdims=True)

        # Cosine similarity (embeddings already normalised)
        scores = (self._clip_embeddings @ query_emb.T).flatten()

        # Get top-k
        top_indices = scores.argsort()[-top_k:][::-1]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < min_score:
                continue
            catalogue_idx = int(self._clip_valid_indices[idx])
            entry = self.images[catalogue_idx].copy()
            entry["score"] = round(score, 3)
            results.append(entry)

        return results

    def _search_tfidf(self, query: str, top_k: int, min_score: float) -> list[dict]:
        """Search using TF-IDF cosine similarity."""
        norm_query = _normalise(query)
        query_vec = self._vectorizer.transform([norm_query])
        scores = cosine_similarity(query_vec, self._tfidf_matrix).flatten()

        top_indices = scores.argsort()[-top_k:][::-1]

        results = []
        for idx in top_indices:
            score = float(scores[idx])
            if score < min_score:
                continue
            entry = self.images[idx].copy()
            entry["score"] = round(score, 3)
            results.append(entry)

        return results

    def _search_simple(self, query: str, top_k: int, min_score: float) -> list[dict]:
        """Search using IDF-weighted word overlap."""
        norm_query = _normalise(query)
        query_words = set(norm_query.split())
        if not query_words:
            return []

        query_weight = sum(self._idf.get(w, 1.0) for w in query_words)

        scored = []
        for i, word_set in enumerate(self._word_sets):
            overlap = query_words & word_set
            if not overlap:
                continue
            overlap_weight = sum(self._idf.get(w, 1.0) for w in overlap)
            doc_weight = sum(self._idf.get(w, 1.0) for w in word_set)
            score = overlap_weight / (query_weight + doc_weight - overlap_weight)
            if score >= min_score:
                scored.append((i, score))

        scored.sort(key=lambda x: -x[1])
        results = []
        for idx, score in scored[:top_k]:
            entry = self.images[idx].copy()
            entry["score"] = round(score, 3)
            results.append(entry)

        return results

    def get_stats(self) -> dict:
        """Return catalogue statistics."""
        formats = Counter(img.get("image_format", "unknown") for img in self.images)
        books = Counter(img.get("source_book", "unknown") for img in self.images)
        with_desc = sum(1 for img in self.images if img.get("description", "").strip())
        return {
            "total_images": self.total,
            "with_descriptions": with_desc,
            "method": self._method,
            "formats": dict(formats),
            "books": len(books),
        }


# Quick CLI test
if __name__ == "__main__":
    import sys

    search = ImageCatalogueSearch()
    stats = search.get_stats()
    print(f"Catalogue loaded: {stats['total_images']:,} images from {stats['books']} books")
    print(f"Search method: {stats['method']}")
    print()

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "A number line from 0 to 10 with 3 and 7 marked"

    print(f"Query: {query}")
    print(f"{'-' * 60}")

    start = time.time()
    results = search.find_matches(query, top_k=5)
    elapsed = time.time() - start

    for i, r in enumerate(results, 1):
        print(f"\n  [{i}] Score: {r['score']:.3f}")
        print(f"      {r['description'][:100]}")
        print(f"      {r['image_url'][:80] if r.get('image_url') else r.get('image_path', 'N/A')[:80]}")
        print(f"      {r['width']}x{r['height']} . {r.get('book_title', '')} . {r.get('idea_title', '')}")

    print(f"\n  Search took {elapsed*1000:.1f}ms")
