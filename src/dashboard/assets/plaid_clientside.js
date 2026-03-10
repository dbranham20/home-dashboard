// assets/plaid_clientside.js
window.dash_clientside = Object.assign({}, window.dash_clientside, {
  plaid: {
    // Opens Plaid Link; on success POSTs /plaid/exchange.
    // Outputs: [linking(bool), exchangedCounter(int)]
    openLink: async function(n_clicks, apiBase, userId, exchangedCounter) {
      if (!n_clicks) {
        return [window.dash_clientside.no_update, window.dash_clientside.no_update];
      }
      try {
        if (typeof Plaid === "undefined" || !Plaid.create) {
          return [false, exchangedCounter];
        }

        // Get link_token
        const ltRes = await fetch(`${apiBase}/plaid/link-token`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: userId }),
        });
        if (!ltRes.ok) return [false, exchangedCounter];
        const lt = await ltRes.json();
        const token = lt.link_token || lt.linkToken || lt.token;
        if (!token) return [false, exchangedCounter];

        // Open Link and wait
        let linking = true;
        const result = await new Promise((resolve) => {
          const handler = Plaid.create({
            token,
            onSuccess: async (public_token) => {
              try {
                const exRes = await fetch(`${apiBase}/plaid/exchange`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ public_token, user_id: userId }),
                });
                resolve({ ok: exRes.ok });
              } catch (e) { resolve({ ok: false }); }
            },
            onExit: () => resolve({ ok: false }),
          });
          handler.open();
        });

        linking = false;
        if (result.ok) return [linking, (exchangedCounter || 0) + 1];
        return [linking, exchangedCounter];
      } catch (e) {
        return [false, exchangedCounter];
      }
    }
  }
});
