# Code Examples

This document contains code snippets to test code chunking strategy.

## Python Example

Here's a Python function:

```python
def calculate_fibonacci(n: int) -> int:
    """Calculate the nth Fibonacci number."""
    if n <= 1:
        return n
    return calculate_fibonacci(n-1) + calculate_fibonacci(n-2)

# Example usage
result = calculate_fibonacci(10)
print(f"Fibonacci(10) = {result}")
```

## JavaScript Example

And here's a JavaScript function:

```javascript
function fetchUserData(userId) {
    return fetch(`/api/users/${userId}`)
        .then(response => response.json())
        .then(data => {
            console.log('User data:', data);
            return data;
        })
        .catch(error => {
            console.error('Error fetching user:', error);
            throw error;
        });
}
```

## Shell Script

```bash
#!/bin/bash
# Deploy script
set -euo pipefail

echo "Starting deployment..."
kubectl apply -f deployment.yaml
kubectl rollout status deployment/myapp
echo "Deployment complete!"
```
