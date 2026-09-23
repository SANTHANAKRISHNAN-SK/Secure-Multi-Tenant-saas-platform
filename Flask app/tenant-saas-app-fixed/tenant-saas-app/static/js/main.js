/* TenantCloud front-end interactions.
   No framework -- vanilla JS kept deliberately small and dependency-free. */

document.addEventListener('DOMContentLoaded', function () {

  // ---- Sidebar toggle (mobile) ----
  const sidebarToggle = document.getElementById('sidebarToggle');
  const sidebar = document.getElementById('sidebar');
  if (sidebarToggle && sidebar) {
    sidebarToggle.addEventListener('click', () => sidebar.classList.toggle('open'));
  }

  // ---- Auto-init & auto-hide Bootstrap toasts ----
  document.querySelectorAll('.toast').forEach(function (toastEl) {
    const toast = new bootstrap.Toast(toastEl, { delay: 5000 });
    toast.show();
  });

  // ---- Animated counters (elements with data-counter="target") ----
  document.querySelectorAll('[data-counter]').forEach(function (el) {
    const target = parseInt(el.getAttribute('data-counter'), 10) || 0;
    const duration = 900;
    const start = performance.now();

    function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(eased * target).toLocaleString();
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  });

  // ---- Password show/hide toggles ----
  document.querySelectorAll('[data-toggle-password]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      const input = document.getElementById(btn.getAttribute('data-toggle-password'));
      if (!input) return;
      const icon = btn.querySelector('i');
      if (input.type === 'password') {
        input.type = 'text';
        icon.classList.remove('fa-eye');
        icon.classList.add('fa-eye-slash');
      } else {
        input.type = 'password';
        icon.classList.remove('fa-eye-slash');
        icon.classList.add('fa-eye');
      }
    });
  });

  // ---- Password strength meter ----
  const newPasswordInput = document.getElementById('new_password');
  const strengthFill = document.getElementById('strengthFill');
  const strengthLabel = document.getElementById('strengthLabel');

  function scorePassword(pw) {
    let score = 0;
    if (pw.length >= 10) score++;
    if (/[A-Z]/.test(pw)) score++;
    if (/[a-z]/.test(pw)) score++;
    if (/\d/.test(pw)) score++;
    if (/[!@#$%^&*()_\-+=[\]{};:'",.<>/?]/.test(pw)) score++;
    return score;
  }

  if (newPasswordInput && strengthFill) {
    newPasswordInput.addEventListener('input', function () {
      const score = scorePassword(newPasswordInput.value);
      const percentages = [8, 25, 50, 75, 100];
      const colors = ['#e11d48', '#e11d48', '#d97706', '#0284c7', '#16a34a'];
      const labels = ['Very weak', 'Weak', 'Fair', 'Good', 'Strong'];
      const idx = Math.max(0, Math.min(score, 5) - 1);
      strengthFill.style.width = (newPasswordInput.value ? percentages[idx] : 0) + '%';
      strengthFill.style.background = colors[idx];
      if (strengthLabel) strengthLabel.textContent = newPasswordInput.value ? labels[idx] : '';
    });
  }

  // ---- Bootstrap form validation ----
  document.querySelectorAll('.needs-validation').forEach(function (form) {
    form.addEventListener('submit', function (event) {
      if (!form.checkValidity()) {
        event.preventDefault();
        event.stopPropagation();
      }
      form.classList.add('was-validated');
    }, false);
  });

  // ---- Simple table search filter (client-side, admin panel) ----
  const tableSearch = document.getElementById('tableSearchInput');
  if (tableSearch) {
    tableSearch.addEventListener('keyup', function () {
      const term = tableSearch.value.toLowerCase();
      document.querySelectorAll('[data-searchable-row]').forEach(function (row) {
        row.style.display = row.textContent.toLowerCase().includes(term) ? '' : 'none';
      });
    });
  }
});
