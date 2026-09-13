-- Subscriptions: the first table a user owns that the ETL must never touch.
--
-- 0009 said why this table was not in it — "Slice 0 is login only; Stripe has
-- its own slice, and a table with no writer is a table whose shape nobody has
-- tested." That slice is here. This migration is the schema half of it and
-- nothing else: no Stripe client, no webhook route, no gating. Those land in
-- their own commits against this shape.
--
-- WHY stripe_subscription_id IS THE PRIMARY KEY
-- --------------------------------------------
-- Same reason fec_candidate_id and bioguide_id are keys elsewhere (§6): when
-- an upstream authority already names the thing, inventing a second id only
-- creates a mapping to keep correct. Stripe names subscriptions, and every
-- event we will ever receive about one carries that name.
--
-- It is also what makes the webhook handler safe to write. Stripe redelivers
-- events, and it does not promise order — `customer.subscription.updated` can
-- arrive before the `created` it follows. A handler that INSERTs is wrong on
-- the second delivery; a handler that UPDATEs is wrong on the first. With the
-- Stripe id as the key, every handler is the same statement:
--
--     INSERT INTO subscription (...) VALUES (...)
--     ON CONFLICT (stripe_subscription_id) DO UPDATE SET ...
--
-- which is correct whatever arrives, however many times. (Out-of-order
-- delivery still needs the handler to not overwrite newer state with older —
-- that is the handler's problem, and the key is what gives it a row to
-- compare against.)
--
-- WHY user_id CASCADES
-- --------------------
-- A subscription with no user is not data, it is a leak: rows naming a
-- stripe_customer_id that nothing can ever resolve to a person. Deleting an
-- account is the one operation that should take them with it, so the FK says
-- so rather than leaving it to whatever code path runs the deletion. This
-- deletes our record, not the Stripe subscription — cancelling the billing
-- side is the application's job on the account-deletion path, and forgetting
-- it means charging someone who no longer has an account.
--
-- WHY THE GRANTS ARE SPELLED OUT HERE
-- -----------------------------------
-- Because the default is wrong for this table, and 0010 said so in advance:
--
--     "new tables are readable by `webapp` and writable by `etl_writer`. That
--      is the right default for a public-data table and the WRONG one for the
--      next identity table — the `subscription` table of §5 will need the
--      0009 treatment, granted to `webapp` and revoked from `etl_writer` in
--      its own migration."
--
-- This is that migration. The ALTER DEFAULT PRIVILEGES in 0010 fire on the
-- CREATE TABLE below and hand etl_writer INSERT/UPDATE/DELETE, so the REVOKE
-- is not belt-and-braces — without it a collector credential could rewrite
-- who is entitled to what. Billing state belongs to the app, in exactly the
-- way identity does (0009): webapp reads and writes, etl_writer sees nothing.
--
-- WHAT THE status CHECK IS FOR
-- ----------------------------
-- The six values are Stripe's own subscription lifecycle, and the set is
-- closed on purpose: a value outside it means we misread a webhook payload,
-- and a failed INSERT is a better way to learn that than a row that silently
-- never matches the gating filter. The path through them is
-- trialing → active → past_due → canceled or unpaid, with incomplete as the
-- entry state when the first payment has not settled yet. §7 grants access on
-- `status ∈ {trialing, active}`; everything else is the same answer, no.
--
-- WHY THERE IS NO UNIQUE (user_id)
-- --------------------------------
-- Because a user with two rows is normal, not corrupt. Cancelling and
-- resubscribing produces a NEW Stripe subscription id, and the old row is
-- history worth keeping — when they were a subscriber, on what plan, until
-- when. Constraining one row per user would force the handler to delete that
-- history to accept a resubscription. "Is this user a subscriber right now" is
-- therefore never a row count; it is the status filter above, which is why
-- idx_subscription_user exists.

-- migrate:up

CREATE TABLE subscription (
  stripe_subscription_id TEXT PRIMARY KEY,
  user_id                TEXT NOT NULL REFERENCES "user" (id) ON DELETE CASCADE,
  stripe_customer_id     TEXT NOT NULL,
  plan                   TEXT,
  status                 TEXT NOT NULL CHECK (status IN
                           ('trialing', 'active', 'past_due', 'canceled', 'unpaid', 'incomplete')),
  current_period_end     TIMESTAMPTZ,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE subscription IS
  'Local mirror of Stripe subscription state. Written only by the webhook route and Checkout return; the ETL has no business here.';
COMMENT ON COLUMN subscription.plan IS
  'Stripe price or product id. Nullable: an incomplete subscription may not have settled on one yet.';
COMMENT ON COLUMN subscription.status IS
  'Stripe lifecycle state. Access is granted on trialing or active only (monetization-design §7).';
COMMENT ON COLUMN subscription.current_period_end IS
  'End of the paid-through period. Nullable, for the same reason plan is: incomplete subscriptions have no period yet.';

-- The gating lookup: WHERE user_id = ? AND status IN ('trialing','active'),
-- issued on every request that guards a paid feature.
CREATE INDEX idx_subscription_user ON subscription (user_id);

-- The webhook lookup. Some events name the customer, not the subscription —
-- `invoice.paid` carries a customer id, and the row it should update has to be
-- found by it.
CREATE INDEX idx_subscription_customer ON subscription (stripe_customer_id);

-- Overrides 0010's ALTER DEFAULT PRIVILEGES for this table. See above.
GRANT SELECT, INSERT, UPDATE, DELETE ON subscription TO webapp;
REVOKE ALL PRIVILEGES ON subscription FROM etl_writer;

-- migrate:down

-- Nothing references subscription, and the grants above are attached to the
-- table, so they go with it — no separate REVOKE needed to leave the roles
-- as 0010 left them.
DROP TABLE IF EXISTS subscription;
