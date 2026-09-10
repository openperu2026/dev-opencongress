(function () {
  const svg = document.getElementById('seatsSvg');
  if (!svg) return;

  const seats = JSON.parse(svg.dataset.seats || '[]');
  if (seats.length === 0) return;

  const tooltip = document.getElementById('seatTooltip');
  const container = document.querySelector('.seats-container');

  svg.setAttribute('viewBox', '0 0 800 300');
  svg.setAttribute('height', 300);

  // Draw circles

  svg.innerHTML = seats.map(s => {
    return `<circle cx="${s.x}" cy="${s.y}" r="${s.r}" fill="${s.color}" data-label="${s.label || ''}"></circle>`;
  }).join('');

  // Tooltip on hover
  document.querySelectorAll('circle').forEach((circle) => {
    circle.addEventListener('mousemove', function(e) {
      if (!circle.dataset.label) return;
      tooltip.style.display = 'block';
      tooltip.setAttribute('aria-hidden', 'false');
      tooltip.textContent = circle.dataset.label;

      const containerRect = container.getBoundingClientRect();
      const tooltipWidth = tooltip.offsetWidth || 120;
      const tooltipHeight = tooltip.offsetHeight || 28;
      let tx = e.clientX - containerRect.left + 12;
      let ty = e.clientY - containerRect.top - tooltipHeight - 10;

      if (tx + tooltipWidth > containerRect.width - 8) {
        tx = e.clientX - containerRect.left - tooltipWidth - 12;
      }
      if (ty < 8) {
        ty = e.clientY - containerRect.top + 14;
      }

      tooltip.style.left = Math.max(8, tx) + 'px';
      tooltip.style.top = Math.max(8, ty) + 'px';
    });

    circle.addEventListener('mouseleave', function() {
      tooltip.style.display = 'none';
      tooltip.setAttribute('aria-hidden', 'true');
    });

  });
})();

(function(){
  const table = document.getElementById('voteMembersTable');
  if (!table) return;

  const tbody = table.querySelector('tbody');
  const buttons = table.querySelectorAll('.vote-sort-button');

  const sortRows = (key, direction) => {
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((left, right) => {
      const leftValue = key === 'vote' ? Number(left.dataset.voteOrder || 0) : (left.dataset[key] || '');
      const rightValue = key === 'vote' ? Number(right.dataset.voteOrder || 0) : (right.dataset[key] || '');

      if (leftValue < rightValue) return direction === 'asc' ? -1 : 1;
      if (leftValue > rightValue) return direction === 'asc' ? 1 : -1;
      return 0;
    });

    rows.forEach((row) => tbody.appendChild(row));
  };

  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      const key = button.dataset.sortKey;
      const nextDirection = button.dataset.direction === 'asc' ? 'desc' : 'asc';

      buttons.forEach((otherButton) => {
        if (otherButton !== button) {
          delete otherButton.dataset.direction;
        }
      });

      button.dataset.direction = nextDirection;
      sortRows(key, nextDirection);
    });
  });
})();
