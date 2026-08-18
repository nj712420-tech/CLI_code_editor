import requests

def list_free_openrouter_models():
    # 1. Ask for the user's OpenRouter API key
    api_key = input("Please enter your OpenRouter API key: ").strip()
    
    if not api_key:
        print("API key cannot be empty. Exiting.")
        return

    # 2. OpenRouter API endpoint for listing models
    url = "https://openrouter.ai/api/v1/models"
    
    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    print("\nFetching models from OpenRouter... Please wait.")
    
    try:
        # 3. Make the API request
        response = requests.get(url, headers=headers)
        response.raise_for_status()  # Check for HTTP errors (e.g., invalid key)
        
        models_data = response.json().get('data', [])
        free_models = []
        
        # 4. Filter for free models
        for model in models_data:
            pricing = model.get('pricing', {})
            
            # Extract pricing strings and convert to float (default to -1 if missing to be safe)
            try:
                prompt_price = float(pricing.get('prompt', -1))
                completion_price = float(pricing.get('completion', -1))
            except ValueError:
                continue
            
            # A model is free if both prompt and completion costs are 0.0
            if prompt_price == 0.0 and completion_price == 0.0:
                free_models.append({
                    "id": model.get("id", "Unknown ID"),
                    "name": model.get("name", "Unknown Name"),
                    "context_length": model.get("context_length", "Unknown")
                })
                
        # 5. Display the results
        if not free_models:
            print("\nNo free models found or API response format changed.")
        else:
            print(f"\nFound {len(free_models)} free models on OpenRouter!\n")
            print("-" * 60)
            for idx, fm in enumerate(free_models, 1):
                print(f"{idx}. {fm['name']}")
                print(f"   Model ID : {fm['id']}")
                print(f"   Context  : {fm['context_length']} tokens")
                print("-" * 60)
                
            print("\nTip: If you want OpenRouter to automatically select the best free model")
            print("for your query, you can use the special model ID: 'openrouter/free'")
                
    except requests.exceptions.HTTPError as http_err:
        print(f"\nHTTP error occurred: {http_err}")
        if response.status_code == 401:
            print("Hint: Your API key might be invalid. Please check and try again.")
    except Exception as err:
        print(f"\nAn unexpected error occurred: {err}")

if __name__ == "__main__":
    list_free_openrouter_models()