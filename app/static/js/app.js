/**
 * Short Game — Alpine.js components
 */

function shortGame() {
    return {
        init() {
            // Global HTMX event listeners
            document.body.addEventListener('htmx:responseError', (e) => {
                console.error('HTMX error:', e.detail);
            });

            // Listen for SSE alert events — trigger confetti on milestones
            document.body.addEventListener('htmx:sseMessage', (e) => {
                try {
                    const data = JSON.parse(e.detail.data);
                    if (data.alert_type === 'MILESTONE_REACHED') {
                        triggerConfetti();
                    }
                } catch (_) {}
            });
        }
    };
}

function triggerConfetti() {
    const colors = ['#ffc107', '#198754', '#0d6efd', '#dc3545', '#6f42c1'];
    for (let i = 0; i < 30; i++) {
        const particle = document.createElement('div');
        particle.className = 'confetti-particle';
        particle.style.left = Math.random() * 100 + 'vw';
        particle.style.top = '100vh';
        particle.style.background = colors[Math.floor(Math.random() * colors.length)];
        particle.style.animationDelay = Math.random() * 0.5 + 's';
        particle.style.animationDuration = (1.5 + Math.random()) + 's';
        document.body.appendChild(particle);
        setTimeout(() => particle.remove(), 2500);
    }
}

function tradeForm() {
    return {
        ticker: '',
        shares: 0,
        amount: 0,
        equity: 10000,
        marginRequired: 0,
        kellyPct: null,
        kellyAmount: 0,
        loading: false,
        executing: false,
        preflightError: null,
        preflightData: {},
        modal: null,

        initFromUrl() {
            const params = new URLSearchParams(window.location.search);
            this.ticker = (params.get('ticker') || '').toUpperCase();

            // Fetch portfolio equity for position sizing
            fetch('/v1/portfolio')
                .then(r => r.json())
                .then(resp => {
                    if (resp.data) {
                        this.equity = parseFloat(resp.data.equity || 10000);
                        // Default to 5% of equity
                        this.amount = Math.floor(this.equity * 0.05);
                        this.calcShares();
                    }
                })
                .catch(() => {});

            // Fetch trade stats for Kelly
            fetch('/v1/trades/stats')
                .then(r => r.json())
                .then(resp => {
                    if (resp.data && resp.data.total_trades >= 20) {
                        // Simple Kelly display
                        const wr = resp.data.win_rate;
                        const avgWin = Math.abs(parseFloat(resp.data.avg_pnl || 0));
                        if (avgWin > 0 && wr > 0) {
                            const kelly = Math.min(25, Math.max(1, wr - (1 - wr)));
                            this.kellyPct = kelly.toFixed(1);
                            this.kellyAmount = this.equity * kelly / 100;
                        }
                    }
                })
                .catch(() => {});
        },

        calcShares() {
            if (this.amount > 0 && this.ticker) {
                // Estimate from amount / assumed price, will be refined by preflight
                // For now use amount directly as share count estimate
                this.shares = Math.max(1, Math.floor(this.amount / 100));
            }
            this.marginRequired = this.amount * 1.5;
        },

        calcAmount() {
            this.amount = this.shares * 100;
            this.marginRequired = this.amount * 1.5;
        },

        async preflight() {
            if (!this.ticker || this.shares < 1) return;
            this.loading = true;
            this.preflightError = null;

            try {
                const resp = await fetch(
                    `/v1/positions/preflight?ticker=${this.ticker}&shares=${this.shares}`
                );
                const data = await resp.json();

                if (!resp.ok) {
                    const errors = data.detail?.errors || data.errors || [];
                    this.preflightError = errors[0]?.message || 'Preflight check failed';
                    return;
                }

                this.preflightData = data.data;
                // Show confirmation modal
                if (!this.modal) {
                    this.modal = new bootstrap.Modal(this.$refs.confirmModal);
                }
                this.modal.show();
            } catch (err) {
                this.preflightError = 'Network error: ' + err.message;
            } finally {
                this.loading = false;
            }
        },

        async executeShort() {
            this.executing = true;
            try {
                const resp = await fetch('/v1/positions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        ticker: this.ticker,
                        shares: this.shares
                    })
                });
                const data = await resp.json();

                if (resp.ok) {
                    if (this.modal) this.modal.hide();
                    window.location.href = '/';
                } else {
                    const errors = data.detail?.errors || data.errors || [];
                    this.preflightError = errors[0]?.message || 'Trade execution failed';
                    if (this.modal) this.modal.hide();
                }
            } catch (err) {
                this.preflightError = 'Network error: ' + err.message;
                if (this.modal) this.modal.hide();
            } finally {
                this.executing = false;
            }
        },

        squeezeBadgeClass(level) {
            const map = {
                'LOW': 'badge bg-success',
                'MODERATE': 'badge bg-info',
                'HIGH': 'badge bg-warning',
                'CRITICAL': 'badge bg-danger',
            };
            return map[level] || 'badge bg-secondary';
        }
    };
}
