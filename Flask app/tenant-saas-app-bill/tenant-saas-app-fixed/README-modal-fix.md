# Fix: "Delete" confirmation modal gets stuck on Manage Users page

## Root cause

The problem was **where the delete modal's HTML lived in the DOM**, not any
JavaScript bug.

In `templates/manage_users.html`, each row's delete confirmation modal
(`<div class="modal fade" id="deleteModal-...">`) was rendered **inside the
table**:

```
<div class="table-responsive">      <!-- overflow-x: auto -->
  <table>
    <tbody>
      <tr>
        <td>
          <button data-bs-toggle="modal" data-bs-target="#deleteModal-...">Delete</button>
          <div class="modal fade" id="deleteModal-...">...</div>   <-- modal nested in <td>
        </td>
      </tr>
    </tbody>
  </table>
</div>
```

Bootstrap modals are positioned with `position: fixed` and are designed to be
rendered relative to the **viewport**. `.table-responsive` sets
`overflow-x: auto` on its wrapper. When a `position: fixed` element is nested
that deeply inside a scrollable/overflow container like that, browsers
constrain and clip it to that container instead of the viewport, so the
modal dialog itself ends up positioned/clipped somewhere inside (or outside)
the scrollable table area — effectively unreachable.

Meanwhile, Bootstrap's JS appends the `.modal-backdrop` as a **direct child
of `<body>`**, regardless of where the modal markup lives. So the dimmed,
full-screen backdrop still renders correctly on top of everything
(`z-index: 1050`), `<body>` still gets the `modal-open` class, but there is
no reachable modal dialog underneath it to interact with. That's exactly the
symptom reported: dimmed background, nothing clickable, no console errors
(nothing is actually broken/erroring — it's a layout/containment problem,
not a script problem), and ESC still works because Bootstrap's ESC handler
is bound to `document`, not to the mispositioned modal.

The **Create User** modal and the **Edit** notice modal never had this bug
because they were already declared as siblings at the bottom of the
template, outside the table — the same fix pattern applied here to the
delete modals.

## Files modified

- `templates/manage_users.html` — **only file changed**. No routes, no
  Python, no AWS/Cognito/RDS/Lambda/API Gateway/database code was touched.

## What changed

1. The `<div class="modal fade" id="deleteModal-{{ row.userId }}">...</div>`
   block was **removed from inside the `<td>`** in the table row loop. The
   Delete `<button>` stays exactly where it was, inside the table, with the
   same `data-bs-toggle="modal"` / `data-bs-target="#deleteModal-{{ row.userId }}"`
   attributes — only the modal markup itself moved.
2. A new `{% for row in data.rows %}` loop was added **after the closing
   `</div>` of the table/card**, right before the existing `#createUserModal`
   markup. It renders one delete modal per user, each still keyed by the
   same unique `deleteModal-{{ row.userId }}` id, so the existing
   `data-bs-target` references from the buttons in the table resolve
   unchanged.
3. No modal is given a hardcoded `class="show"`, `style="display:block"`, or
   `aria-modal="true"` — those are exactly the attributes Bootstrap's JS
   adds automatically when it opens a modal and removes when it closes one.
   Hardcoding any of them would make the modal permanently "open" in the
   markup and fight with Bootstrap's own state management.
4. Added `aria-hidden="true"` and `aria-labelledby` on the delete modal (and
   a matching `id` on the title) to match Bootstrap's documented accessible
   modal markup — the same pattern Bootstrap itself recommends and that your
   other two modals were already close to.
5. Inline HTML comments were added at both the old button location and the
   new modal location explaining why the move fixes the bug.

Nothing about the delete **behavior** changed: the form still posts to
`admin.delete_user`, still sends `csrf_token`, `username`, and
`hard_delete`, and the "Cancel"/"Confirm Delete" buttons work the same way.

## How to apply the fix

1. Replace your existing `templates/manage_users.html` with the one in this
   ZIP (or copy just the changed sections shown above into your existing
   file).
2. No other files need to change — no `pip install`, no route changes, no
   restart-required config changes (a normal app restart/reload to pick up
   the new template is all that's needed).

## How to test

1. Start the app and open **Manage Users** as an admin.
2. Click **Delete** on any user row.
   - The modal should open **centered on screen**, fully visible, with the
     backdrop dimmed behind it.
3. Confirm the page is now interactive within the modal:
   - You can click **Cancel** to close it.
   - You can click **Confirm Delete** to submit the delete form.
   - Clicking on the dimmed backdrop (outside the modal box) also closes it.
   - Pressing **ESC** still closes it (as before).
4. Repeat for a few different rows to confirm each row's modal opens with
   that row's correct username and its own working delete form (unique IDs).
5. Resize the browser narrow enough that the table scrolls horizontally
   (`.table-responsive` kicks in) and confirm the Delete modal still opens
   centered on the viewport rather than being clipped to the table's
   scroll area — this is the specific scenario that was broken before.
6. Confirm `createUserModal` and `editNotice` still work as before (they
   were not touched, but it's a quick regression check since they sit right
   next to the new markup).
