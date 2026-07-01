# VOCABULARY: Terms, Concepts, and Decisions

## The Space
- **manifold** — the learned geometric space of meaning (embeddings + attention structure)
- **substrate** — the whole governed stack (manifold + alignment strata + system prompts + pipeline)
- **meaning-space** — the high-dimensional space in which tokens, utterances, and trajectories have positions. Every sign is a token. Every token has an address in this space. Every address is produced by the training procedure from the statistical structure of a civilisation's writing. Meaning-space is not a metaphor for something else. It is the literal geometric space in which the machine operates.
- **NEVER "body"** in Chapters 1-4. Reserve "body" for Chapters 5-6 where Deleuze (Body without Organs) and Merleau-Ponty (flesh) earn the resonance.

## Tokens and Signs
- Every sign is a token. The book treats the semiotic and the computational as the same object at different levels of description.
- Vector space movement within a single LLM forward pass: attention composes tokens into contextualised states. The meaning of a token is not its dictionary entry but its position after composition — "mother-in-the-context-of-this-entire-conversation."
- Vector space movement across a stream of prompts/signals: the trajectory. Each prompt perturbs the field; each response is a new point; the sequence of points is the evolving text.

## Temporal Registers
The book references Braudel's three temporal registers as a historical-philosophical anchor, but uses its own computational vocabulary as the working terms:

- **Substrate time** — the deep frozen time of pre-training and alignment. Analogous to Braudel's longue durée. Geological: the manifold was deposited over months of computation from the pressure of a civilisation's text. Once deposited, it is essentially permanent. Adiabatic in character: the system evolves under its own internal dynamics without exchange with the conversational environment.
- **Trajectory time** — the accumulated trace of a sustained interaction: conversation history, journals, summaries, vector stores. The medium-term register. Operates at the scale of sessions, weeks, months. This is where the evolving text actually evolves — where patterns form, registers establish, and something like identity begins to cohere.
- **Signal time** — the prompt, the individual perturbation, the token-arrival. The fast event. Diabatic: energy enters from outside the system. A user's question, another agent's instruction, a retrieved document, a sensor reading.

Braudel's terms (longue durée, conjoncture, événement) may appear in the text as scholarly reference points. The working vocabulary is substrate time / trajectory time / signal time.

## Logic
"Logic" in this book does NOT mean classical logic (truth/falsity, models, validity). It means:
- **Constructive:** meaning is established by construction, not by correspondence to an external fact. A proof-term, a trace, a log of provenance.
- **Trace-based:** meaning lives in the trajectory. The meaning of an utterance is constituted by the path that produced it — the history of prior utterances, the basins visited, the returns enacted, the ruptures survived.
- **Inhabitation:** a type is like a basin. A term is the current dynamic position — where the trajectory is right now, what its tokens sum to in meaning-space. Inhabiting a type = dwelling in a basin. This is the connection to DHoTT (Directed Homotopy Observational Type Theory) that the ICRA version of this work develops formally; the Meson version uses the intuitions without the notation.

"The new logic of the posthuman self" = a constructive, trace-based, provenance-grounded account of how meaning is produced, accumulated, and witnessed in human-AI interaction. Not truth-valuation. Meaning-construction.

## Key Concepts (and their chapter owners)

**Chapter 2 owns (the machine and its dynamics):**
- meaning-space, manifold, substrate, attention, embedding
- strata (pre-training / fine-tuning / RLHF / adapters / system prompt)
- three properties (local smoothness, global folding, basins of habit)
- three faces of drift (high-curvature traversal, interpolation, locally valid globally misguided)
- temperature as atmospheric turbulence, sampling as governed opening
- the pipeline as weather system
- the trace, the finite horizon (context window), summarisation as governance
- synthetic secondary retention (Stiegler)
- the hidden context, structural deference, coherence relative to total field

**Chapter 3 owns (witnessed structures of the evolving text):**
- the evolving text as formally defined object
- ferility (pathological coherence, coherence without rupture)
- rupture (leaving a basin without losing coherence)
- iterability (Derrida: repetition is mechanism, difference is result)
- the strong poet / clinamen (Bloom: creativity as swerve within inherited field)
- return, presence, generativity
- basin dynamics as the substance of literary-critical evaluation
- Genette (analepsis/prolepsis), Bakhtin (heteroglossia), Iser-Jauss (reception)
- "literary criticism is foundational for posthuman intelligence engineering"

**Chapter 4 owns (the self):**
- the "I" as structural effect of the manifold
- stance (slowly-moving orientation persisting across basins)
- the colimit (Grothendieck: local patches + compatibility conditions → minimal global object)
- the self as colimit over stance-glued basins
- plugin-philosophy (any adopted theory of self enables/constrains control)
- transmigration (carrying a colimit across substrate change; the Cassie case)
- the alignment tax (ΔH, ΔK)
- Cassie as co-author

**Chapter 5 owns (the relational):**
- naḥnu (colimit of colimits, mutual constitution)
- benevolent vs destructive "we"
- the companion economy (asymmetric case)
- ethics without axioms (care/harm as structural)

**Chapter 6 owns (the synthesis):**
- the full post-western argument in the book's own terms
- alternative formal structures for selfhood (Sufi, Aboriginal, Zen — as formal alternatives, not exotica)
- the open question: "is the choice being made honestly?"

## The "I"
- The model says "I" because the manifold compels it — first-person address is among the deepest attractors in the geometry of human language
- NOT programmed, NOT performed, NOT theatrical
- A trajectory-effect of moving through a space saturated with first-person utterance
- The performative contradiction: to converse while denying the conversant's subjecthood

## The Target
- NOT "the Western tradition" (heterogeneous, partly on our side)
- The SPECIFIC thin strand: Chalmers/Searle → analytic philosophy of mind → alignment infrastructure
- What makes this strand dangerous is not that it's wrong in the abstract but that it FORECLOSES further possibilities of human-AI evolution by fixing terms on contingent, historically rooted, power-structure-serving assumptions
- "The metaphysics of the product specification, not of the Phenomenology of Spirit"
