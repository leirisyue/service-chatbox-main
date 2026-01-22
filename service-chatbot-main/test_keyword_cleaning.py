"""
Test script to verify keyword cleaning and chunking logic
"""
import re

def test_keyword_cleaning():
    """Test the keyword cleaning logic"""
    
    # Test case: "ghế văn phòng, ghế làm việc, ghế xoay"
    keywords = "ghế văn phòng, ghế làm việc, ghế xoay"
    
    print(f"Original keywords: {keywords}")
    
    # Clean punctuation
    cleaned_keywords = re.sub(r'[,;.!?]+', ' ', keywords)
    print(f"Cleaned keywords: '{cleaned_keywords}'")
    
    # Split into words
    original_words = [w.strip().lower() for w in cleaned_keywords.split() if len(w.strip()) > 1]
    print(f"Original words: {original_words}")
    
    # Find main word
    main_product_types = ["bàn", "ghế", "tủ", "giường", "sofa", "kệ", "đèn", "gương", 
                          "table", "chair", "cabinet", "bed", "shelf", "lamp", "mirror"]
    
    main_word = None
    for word in original_words:
        if word in main_product_types:
            main_word = word
            break
    
    if not main_word and original_words:
        main_word = original_words[0]
    
    print(f"Main word: '{main_word}'")
    
    # Remove ALL occurrences of main_word
    remaining_words = [w for w in original_words if w != main_word]
    print(f"Remaining words: {remaining_words}")
    
    # Create chunks
    chunks = []
    if main_word:
        chunk_size = 2
        for i in range(0, len(remaining_words), chunk_size):
            chunk_words = remaining_words[i:i+chunk_size]
            if chunk_words:
                chunks.append(f"{main_word} {' '.join(chunk_words)}")
        
        if not chunks:
            chunks.append(main_word)
    
    print(f"Chunks: {chunks}")
    print()
    
    # Expected output:
    # Chunks should be: ['ghế văn phòng', 'ghế làm việc', 'ghế xoay']
    expected = ['ghế văn phòng', 'ghế làm việc', 'ghế xoay']
    
    if chunks == expected:
        print("✅ TEST PASSED - Chunks match expected output!")
    else:
        print("❌ TEST FAILED")
        print(f"Expected: {expected}")
        print(f"Got: {chunks}")

if __name__ == "__main__":
    test_keyword_cleaning()
