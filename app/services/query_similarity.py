from app.services.jaccard_scoring import score_jaccard

def compute_query_similarity_matrix(queries: list[str]) -> list[list[float]]:
    """
    Computes a pairwise similarity matrix for a batch of strings.
    Optimized to compute only the upper triangle since the metric is symmetric.
    """
    n = len(queries)
    matrix = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    
    for i in range(n):
        for j in range(i + 1, n):
            score = score_jaccard(queries[i], queries[j])
            matrix[i][j] = score
            matrix[j][i] = score
            
    return matrix
