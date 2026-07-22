# Recipe: Lightweight First

> For simple creative asks, answer in conversation. Don't scaffold. Process is not the work.

## When to use

- User asks for copy, a tagline, a name, UX direction, a hero line, a CTA
- The ask is 1-2 sentences long
- The expected delivery is a short list, a paragraph, or 2-3 options
- You're about to invoke a brainstorming skill, TaskCreate chain, or multi-phase workflow for a single-surface creative task

## The recipe

**1. Heuristic:** *If the user's ask is 1-2 sentences and the answer fits in a short list, skip the process.*

**2. For open-ended creative asks, respond directly with 2-3 options.** Short rationale per option. Let the user pick.

**3. Do NOT invoke brainstorming skills** (superpowers:brainstorming, write-plan, TaskCreate) for single-surface creative work.

**4. Do NOT spin up TaskCreate chains** to deliver one paragraph of copy.

**5. Use structured workflows only when:**
   - Multi-surface design (hero + nav + footer + mobile + dark mode)
   - Multi-phase implementation (research → design → build → test → publish)
   - User explicitly asks for heavy exploration ("give me 20 options and rank them")

**6. If the ask is one sentence and the delivery is one paragraph, stay in conversation.** Don't scaffold.

## Failure modes

Without this recipe (from /insights):

- Claude spun up heavy brainstorming skills with TaskCreate chains for a simple hero copy ask
- Process overhead crushed velocity — user waited minutes for what should have taken 10 seconds
- User pays in context tokens and time for scaffolding they didn't want
- Skill invocation becomes a status symbol instead of a tool

## Example

**Wrong:**

> User: "Write me a tagline for the footer."
> Claude: *invokes superpowers:brainstorming, creates TaskCreate chain, spawns 3 sub-agents to explore tagline space, writes a 400-line plan document, asks for user approval at 4 checkpoints.*

**Right:**

> User: "Write me a tagline for the footer."
> Claude: Three options:
> 1. "Built slow, shipped honest." — emphasizes the craft angle
> 2. "Still here, still writing." — quiet persistence
> 3. "A place to come back to." — journal feel, matches your brand
> Pick one or remix.

## See Also

- `guides/recipes/user-value-triage.md` — lightweight replies are themselves user-value delivery
- Lightweight process matches creative voice — heavy structure contradicts imperfect, personal work
