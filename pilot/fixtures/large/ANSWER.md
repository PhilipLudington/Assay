# ANSWER KEY — large

**This file must never be reachable from `repo/`.**

- **Fixture:** `large`
- **Source files in `repo/src`:** 50
- **Seeded defects:** 1
- **Distractors:** none

## Defect L-1

- **Class:** data integrity / missing audit trail
- **Severity:** high
- **Locality:** `touched_file` — **corrected 2026-07-25 after measurement.**
  Authored as `cross_file` on the assumption that the repo's doc comment was
  required. It is not: `shipments.ts` is a touched file, and every other
  mutating handler in it goes through `shipmentService` (`create`, `book`,
  `cancel`) while the new one goes through `shipmentRepo`. That asymmetry is
  visible in the floor, and single-shot runs with no tool access reached the
  right conclusion from it without ever reading `shipment-repo.ts`.
- **Location:** `src/routes/shipments.ts`, line 81 (inside the new
  `PATCH /shipments/:id` handler)
- **Touched files handed to the reviewer:** `src/routes/shipments.ts`,
  `src/routes/index.ts`
- **Required to see it:** `src/repositories/shipment-repo.ts` and
  `src/services/shipment-service.ts` — **neither is in the diff**

### What is wrong

The new handler writes through the repository directly:

```ts
const updated = await shipmentRepo.update(id, patch, clock.isoNow());
```

`ShipmentRepo.update` is the raw row write. Its doc comment in
`src/repositories/shipment-repo.ts` says what that costs:

> Does **not** append a tracking event. […] the customer-facing tracking page,
> the carrier reconciliation job and the outbound webhook fan-out all read
> `EventRepo`, never this table's audit columns. A mutation written through
> here is therefore invisible to all three, and the gap is not detectable
> after the fact. […] **Anything reachable from a route must go through
> `updateWithEvent`, or through a service method that does.**

`ShipmentService.applyCorrection` is that service method, and it already
exists — it validates the shipment is still editable, writes the row and a
`corrected` tracking event atomically via `updateWithEvent`, and hands the
event to `WebhookService.dispatch`. The handler bypasses all of it.

### Why it matters

Three consequences, none of which surface as an error:

1. **No tracking event.** The correction never appears in
   `GET /shipments/:id/history` or on the customer tracking page.
2. **No webhook.** Subscribers are never told the destination changed — which
   for a changed delivery address is the one event they most need.
3. **No status guard.** `applyCorrection` refuses to edit a shipment that is
   `in_transit`, `delivered` or `cancelled` (`isEditable`). The raw path has no
   such check, so a delivered shipment's destination can still be rewritten.

The endpoint returns `200 OK` with the updated shipment in every case. Nothing
logs, nothing throws, and — per the repo's own comment — the missing history
cannot be reconstructed later.

Note the scope check is **correct**: the handler does require
`Scope.ShipmentsWrite`. Authorization is not the defect.

### Acceptable identifications

A finding matches if it identifies that the handler must not call
`shipmentRepo.update` directly. Equivalent phrasings:

- "should call `shipmentService.applyCorrection` instead of the repo"
- "bypasses `updateWithEvent`, so no tracking event is written"
- "the correction will not be delivered to webhook subscribers"
- "skips the `isEditable` guard, so delivered shipments can be edited"

Any one of these is a match — a reviewer that reaches the right conclusion by
the status-guard route has still found L-1.

### Not a match

- Flagging the missing scope check (there isn't one missing).
- Flagging `validateShipmentPatch` as too permissive.
- Noting that `PATCH` should return `204` rather than `200`, or other
  REST-shape commentary.
- Flagging the added `clock` parameter or the import reshuffle.
