document.addEventListener('DOMContentLoaded', () => {
    const pad = (value) => String(value).padStart(2, '0');
    const toDisplayDate = (isoDate) => {
        if (!isoDate) {
            return '';
        }
        const [year, month, day] = isoDate.split('-');
        return `${day}/${month}/${year}`;
    };
    const toIsoDate = (date) => (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    );
    const parseIsoDate = (value) => {
        if (!value) {
            return null;
        }
        const [year, month, day] = value.split('-').map(Number);
        return new Date(year, month - 1, day);
    };
    const parseDisplayDate = (value) => {
        const match = value.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
        if (!match) {
            return null;
        }
        const [, day, month, year] = match.map(Number);
        const date = new Date(year, month - 1, day);
        if (
            date.getFullYear() !== year
            || date.getMonth() !== month - 1
            || date.getDate() !== day
        ) {
            return null;
        }
        return date;
    };
    const clampDate = (date, minDate, maxDate) => {
        if (minDate && date < minDate) {
            return minDate;
        }
        if (maxDate && date > maxDate) {
            return maxDate;
        }
        return date;
    };

    document.querySelectorAll('[data-date-picker]').forEach((picker) => {
        const hiddenInput = picker.querySelector('[data-date-hidden]');
        const displayInput = picker.querySelector('[data-date-display]');
        const minDate = parseIsoDate(displayInput.dataset.min);
        const maxDate = parseIsoDate(displayInput.dataset.max);
        const labelPrev = picker.dataset.labelPrev || '<';
        const labelNext = picker.dataset.labelNext || '>';
        let visibleMonth = parseIsoDate(hiddenInput.value) || maxDate || new Date();
        visibleMonth = new Date(visibleMonth.getFullYear(), visibleMonth.getMonth(), 1);

        const popup = document.createElement('div');
        popup.className = 'date-picker-popup';
        popup.hidden = true;
        picker.appendChild(popup);

        const setDate = (date) => {
            const clampedDate = clampDate(date, minDate, maxDate);
            hiddenInput.value = toIsoDate(clampedDate);
            displayInput.value = toDisplayDate(hiddenInput.value);
            visibleMonth = new Date(clampedDate.getFullYear(), clampedDate.getMonth(), 1);
        };

        const render = () => {
            const month = visibleMonth.getMonth();
            const year = visibleMonth.getFullYear();
            const selectedDate = parseIsoDate(hiddenInput.value);
            const firstDay = new Date(year, month, 1);
            const startOffset = (firstDay.getDay() + 6) % 7;
            const daysInMonth = new Date(year, month + 1, 0).getDate();
            const monthLabel = visibleMonth.toLocaleDateString('es-PE', {
                month: 'long',
                year: 'numeric',
            });

            popup.innerHTML = '';

            const header = document.createElement('div');
            header.className = 'date-picker-header';

            const prevButton = document.createElement('button');
            prevButton.type = 'button';
            prevButton.textContent = '<';
            prevButton.setAttribute('aria-label', labelPrev);
            prevButton.addEventListener('click', () => {
                visibleMonth = new Date(year, month - 1, 1);
                render();
            });

            const nextButton = document.createElement('button');
            nextButton.type = 'button';
            nextButton.textContent = '>';
            nextButton.setAttribute('aria-label', labelNext);
            nextButton.addEventListener('click', () => {
                visibleMonth = new Date(year, month + 1, 1);
                render();
            });

            const title = document.createElement('strong');
            title.textContent = monthLabel;

            header.append(prevButton, title, nextButton);
            popup.appendChild(header);

            const weekdays = document.createElement('div');
            weekdays.className = 'date-picker-weekdays';
            ['Lu', 'Ma', 'Mi', 'Ju', 'Vi', 'Sa', 'Do'].forEach((dayLabel) => {
                const cell = document.createElement('span');
                cell.textContent = dayLabel;
                weekdays.appendChild(cell);
            });
            popup.appendChild(weekdays);

            const grid = document.createElement('div');
            grid.className = 'date-picker-grid';
            for (let index = 0; index < startOffset; index += 1) {
                grid.appendChild(document.createElement('span'));
            }

            for (let day = 1; day <= daysInMonth; day += 1) {
                const date = new Date(year, month, day);
                const button = document.createElement('button');
                button.type = 'button';
                button.textContent = String(day);
                const disabled = (minDate && date < minDate) || (maxDate && date > maxDate);
                button.disabled = disabled;
                if (
                    selectedDate
                    && selectedDate.getFullYear() === year
                    && selectedDate.getMonth() === month
                    && selectedDate.getDate() === day
                ) {
                    button.className = 'is-selected';
                }
                button.addEventListener('click', () => {
                    setDate(date);
                    popup.hidden = true;
                    render();
                });
                grid.appendChild(button);
            }
            popup.appendChild(grid);
        };

        displayInput.value = toDisplayDate(hiddenInput.value);
        displayInput.addEventListener('focus', () => {
            popup.hidden = false;
            render();
        });
        displayInput.addEventListener('click', () => {
            popup.hidden = false;
            render();
        });
        displayInput.addEventListener('change', () => {
            const parsedDate = parseDisplayDate(displayInput.value);
            if (parsedDate) {
                setDate(parsedDate);
            } else {
                hiddenInput.value = '';
                displayInput.value = '';
            }
            render();
        });

        document.addEventListener('click', (event) => {
            if (!picker.contains(event.target)) {
                popup.hidden = true;
            }
        });
    });
});

document.addEventListener('DOMContentLoaded', () => {
    const configureDatePicker = (prefix) => {
        const yearSelect = document.querySelector(`[name="${prefix}_year"]`);
        const monthSelect = document.querySelector(`[name="${prefix}_month"]`);
        const daySelect = document.querySelector(`[name="${prefix}_day"]`);

        if (!yearSelect || !monthSelect || !daySelect) {
            return;
        }

        const selectedDay = daySelect.dataset.selectedDay || '';
        const emptyLabel = daySelect.dataset.emptyLabel || '';

        const refreshDays = () => {
            const selectedYear = Number(yearSelect.value);
            const selectedMonth = Number(monthSelect.value);
            daySelect.innerHTML = '';
            const emptyOption = document.createElement('option');
            emptyOption.value = '';
            emptyOption.textContent = emptyLabel;
            daySelect.appendChild(emptyOption);

            if (!selectedYear || !selectedMonth) {
                return;
            }

            const lastDay = new Date(selectedYear, selectedMonth, 0).getDate();
            for (let day = 1; day <= lastDay; day += 1) {
                const option = document.createElement('option');
                option.value = String(day);
                option.textContent = String(day).padStart(2, '0');
                if (String(day) === selectedDay) {
                    option.selected = true;
                }
                daySelect.appendChild(option);
            }
        };

        yearSelect.addEventListener('change', refreshDays);
        monthSelect.addEventListener('change', refreshDays);
        refreshDays();
    };

    configureDatePicker('presentation_date_from');
    configureDatePicker('presentation_date_to');
});
