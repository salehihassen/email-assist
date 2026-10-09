const form = document.getElementById('login-form');
const submit = document.getElementById('login-submit');
const error = document.getElementById('login-error');
const password = document.getElementById('login-password');
form.addEventListener('submit', async event => {
  event.preventDefault();
  if (submit.disabled) return;
  submit.disabled = true;
  submit.textContent = 'Signing in…';
  error.textContent = '';
  try {
    const response = await fetch('/api/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {'Content-Type': 'application/json', 'X-Email-Assist': '1'},
      body: JSON.stringify({
        username: document.getElementById('login-username').value,
        password: password.value,
        next: new URLSearchParams(location.search).get('next') || '/',
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(typeof result.detail === 'string' ? result.detail : 'Unable to sign in. Please try again.');
    }
    password.value = '';
    // Server accepts only the inbox and its email permalinks.
    location.replace(result.next);
  } catch (failure) {
    error.textContent = failure.message;
    password.value = '';
    password.focus();
  } finally {
    submit.disabled = false;
    submit.textContent = 'Sign in';
  }
});
