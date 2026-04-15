function buildPieChart(canvasId, labels, values) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) {
        return;
    }

    new Chart(ctx.getContext('2d'), {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [
                {
                    data: values,
                    backgroundColor: [
                        '#38bdf8',
                        '#fb7185',
                        '#facc15',
                        '#34d399',
                        '#a855f7',
                        '#f97316',
                    ],
                    borderColor: '#0f172a',
                    borderWidth: 2,
                },
            ],
        },
        options: {
            responsive: false,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    labels: {
                        color: '#e2e8f0',
                    },
                },
            },
        },
    });
}
