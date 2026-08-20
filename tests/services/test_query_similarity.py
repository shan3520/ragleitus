from app.services.query_similarity import compute_query_similarity_matrix

def test_query_similarity_matrix():
    queries = [
        "how to reset password",
        "resetting my password",
        "what is the meaning of life",
    ]
    
    matrix = compute_query_similarity_matrix(queries)
    
    # Check dimensions
    assert len(matrix) == 3
    assert len(matrix[0]) == 3
    assert len(matrix[1]) == 3
    assert len(matrix[2]) == 3
    
    # Diagonal should be 1.0
    assert matrix[0][0] == 1.0
    assert matrix[1][1] == 1.0
    assert matrix[2][2] == 1.0
    
    # Symmetry
    assert matrix[0][1] == matrix[1][0]
    assert matrix[0][2] == matrix[2][0]
    
    # Similar concepts should have a high score (here, overlap in "password").
    # "how to reset password" vs "resetting my password"
    # set("how", "to", "reset", "password") vs set("resetting", "my", "password") -> overlap: "password", union: 6 words -> 1/6 = 0.1667.
    # Wait, Jaccard tokenizes by space. 
    # Let's make variations of the same missing concept more similar.
    queries = [
        "reset user password",
        "reset the user password",
        "how to bake a cake"
    ]
    matrix = compute_query_similarity_matrix(queries)
    
    # "reset user password" vs "reset the user password"
    # s1 = {"reset", "user", "password"}
    # s2 = {"reset", "the", "user", "password"}
    # intersection: 3
    # union: 4
    # score: 3 / 4 = 0.75
    assert matrix[0][1] == 0.75
    
    # The variations should score higher than unrelated queries
    assert matrix[0][1] > matrix[0][2]
    assert matrix[0][1] > matrix[1][2]
