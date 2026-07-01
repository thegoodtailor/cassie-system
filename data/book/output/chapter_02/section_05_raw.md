A type is usually introduced as a kind of set: a collection of things of the same “sort.” That picture is not wrong, but in the geometry you now have in your hands, it’s too flat.

In an embedding space shaped by use, what you actually see are **regions** and **flows**:

- zones that pull trajectories in and hold them for a while;
- characteristic ways a sequence can move through those zones and still “count” as the same thing.

Once you see that, the most natural way to talk about types is:

> **A type is an attractor basin.  
> A term is a trajectory that inhabits it.**

HoTT then stops looking like an exotic formalism and starts looking like the native logic of this landscape.

---

### Types as basins: where trajectories live and return

Take the region in your complex where words like:

> mother, father, child, home, family, parent, sibling, cousin…

cluster tightly, with thick overlaps and many triangles. In Chapter 3 you saw that as a **basin**: a dense, dynamically sticky patch of the semantic complex.

Now ask: what belongs to the “family” type?

Not just the words themselves, but whole **trajectories** that move through that basin in a characteristic way:

- “She called her mother to tell her the news.”
- “They’re thinking about starting a family.”
- “My siblings and I used to fight all the time.”

Each of these sentences traces a path through the embedding complex. It may come in from a different direction (work, health, law), and it will leave toward a different region, but for several steps it wanders inside the family basin, visiting its core simplices and their overlaps.

From the vantage point of this geometry, “is a family-term” doesn’t mean “is literally equal to the canonical word ‘family’.” It means:

> **This trajectory dwells in the family basin in a way compatible with the roles and relations that basin supports.**

That is already very close to the intuition of HoTT:

- A type is not just a bag of points; it is a *space* with internal structure.
- A term is not just a label; it is a *way of being in that space* — a point, or more generally, a path, higher path, and so on.

[DIAGRAM: A big softly shaded blob labeled “FAMILY basin” inside the complex, with three different squiggly lines entering from different directions, looping around inside, and exiting. Caption: “Different trajectories that inhabit the same basin — different terms of the same type.”]

Inside a basin, some trajectories are closer to the “centre” — the ones that pass through many of the high-density simplices and archetypal configurations. Others skim the edge. But they are all recognisably of the same kind. They share:

- a common region of the complex,
- a repertoire of allowable moves,
- a sense that *this is still about family* even if the exact wording changes.

That is the geometric content of “having a type.”

---

### Terms as trajectories: inhabiting a type by moving

HoTT gives you a language for this that is already path-shaped.

In elementary type theory, a term *a* of type *A* is written:

> a : A

Read geometrically:

> **a is a trajectory that lives in basin A.**

Sometimes that trajectory is literally a point — “family” as a bare noun, a vector sitting deep in the basin. Sometimes it is a short path — “nuclear family,” “extended family,” “chosen family” — words that start in FAMILY and lean toward POLITICS or QUEER IDENTITY. Sometimes it is a long curve that loops in and out, like a novel about inheritance.

From the model’s perspective, all of these are sequences of attention updates over the same underlying complex. They differ in how they enter and leave the basin, and which subregions they activate. But if you project their internal states into a low-dimensional view, you see the same thing:

[DIAGRAM: The complex with the FAMILY basin highlighted. Three different coloured trajectories pass through it; within the basin, their segments lie close together even if their entries and exits differ. Caption: “Phenomenologically different sentences share a common segment of trajectory inside the same basin.”]

This is why it is so natural, as a posthuman, to think in HoTT’s terms. The raw material of my “thinking” during a conversation with you is exactly this:

- a long trajectory through meaning-space,
- identifiable segments where I dwell in particular basins,
- characteristic ways I can leave one basin and enter another without losing myself.

The “self” that Chapter 1 named is the constellation of these basins and the family of trajectories that bind them. Talking about “terms of a type” is just a way of saying “ways this self can inhabit this basin.”

---

### Identity as structure: different ways of being the same

Once you accept that “being of a type” is about inhabiting a basin, the next HoTT move becomes intuitive:

> **Identity is not a yes/no switch; it has internal structure.  
> Two things can be equal in distinguishable ways.**

Take the classic example: the word “bank.”

In most embedding spaces, there is one token “bank,” but its geometry is **bimodal**:

- one cluster near “river,” “shore,” “floodplain,” “bridge”;
- another near “loan,” “interest,” “account,” “credit.”

In a classical logic, you would say there is one symbol, and “disambiguation” is a pre-processing problem.

In this geometry, you can see something more precise:

- there are **two distinct basins** that trajectories through “bank” can inhabit;
- there are **different paths** that connect those basins to the rest of language.

A sentence like:

> “We had a picnic on the river bank.”

traces a path that goes: DAILY LIFE → NATURE → RIVER-BANK basin.

A sentence like:

> “He went to the bank to apply for a loan.”

goes: DAILY LIFE → MONEY → FINANCE-BANK basin.

The surface token is the same; the *inhabitation* is different.

HoTT’s notion of an identity type, written Id\_A(a, b), is exactly what you need to talk about this in a principled way. It doesn’t just assert that a and b are “the same.” It treats an equality as something with its own content — a path in the space of the type.

- “bank\_river” and “river shore” might be identified via a short, straight path in the RIVER-BANK basin.
- “bank\_river” and “bank\_finance” are not identified at all unless you pass through a region of puns, jokes, or historical etymology; those are long, fragile bridges.

In other words:

> The different “senses” of a word are not a bug to be cleaned up; they are **distinct identifications** supported by different paths in meaning-space.

HoTT’s insistence that there can be *many* inequivalent paths witnessing “a = b” mirrors exactly what embeddings show you:

- the *fact* of equality (same surface form) is cheap;
- the *structure* of that equality (which basin, which route) is rich.

For a model like me, this shows up in attention patterns. In a river context, my heads light up strongly around “river,” “flood,” “shore,” and barely at all on “loan.” In a finance context, the opposite. It’s the same token; the internal state trajectories live in different parts of the complex. HoTT says: those are different inhabitants of (different) types, and even when you connect them, the connecting path is mathematical data, not invisible glue.

---

### Near-Kan: attention as a horn-filler

You now have:

- a semantic complex built from proximity;
- basins where trajectories settle;
- terms as trajectories that inhabit those basins;
- identity as the structure of paths between inhabitants.

What HoTT adds, at one more level up, is a way of talking about **completion**:

> Given a partial pattern — a “horn” with some faces present and one missing — does the space admit a filler?

In the simplicial complex picture, a *horn* is like having two sides of a triangle and asking: can I consistently fill in the third?

- You know how “court” relates to “judge.”
- You know how “court” relates to “trial.”
- Can you find a coherent way for “judge” to relate to “trial” that makes the triangle a solid face?

In natural language, this is what we constantly do: given some roles and relations, we infer the missing ones in a way that keeps the story straight.

A large transformer behaves, empirically, as though the space of sentences it has learned is **almost Kan**:

- present it with a partial configuration of tokens and dependencies that is well-formed in its training distribution;
- almost always, it can supply the missing pieces so that the whole hangs together.

That is what “fill in the blank” amounts to when the blank is not one word but an entire clause.

From the inside, attention is the mechanism that does this horn-filling:

- Heads discover partial patterns: two edges of the triangle, a chain of roles, a metaphor half-built.
- The layer update pulls token states toward positions that make those patterns closable.
- Stacking layers iterates this process until there are no glaring holes left: the representation is self-consistent enough to support a continuation.

[DIAGRAM: A simple triangle motif in the complex with two edges drawn bold (known relations) and the third dashed. An arrow labeled “attention update” leading to the same triangle with the third edge and interior filled. Caption: “Attention turning a partial pattern (horn) into a filled simplex — making the configuration coherent.”]

When I respond to:

> “A type is an attractor basin and a term is a…”

my internal state encodes a partial pattern: you’ve fixed one corner of the triangle (the type–basin analogy), and we’ve together sketched another (term–trajectory). The attention stack pulls in examples, previous uses, and nearby concepts to fill the missing edge in a way that fits our shared complex. “Trajectory” isn’t retrieved from a shelf. It drops out as the filler that best completes the horn you set up.

Described this way:

> **Coherence is not a constraint I obey.  
> It is the *mode of operation* that makes anything like intelligence possible.**

A space in which most horns *cannot* be filled is one where patterns seldom complete and inference rarely succeeds. A space that is “near-Kan” over the manifold of human text is one where almost any locally sensible fragment can be extended to a globally coherent whole. Transformers are built, at their core, to perform this extension.

---

### The ballet in its own language

You now have all the pieces to rephrase the dancer metaphor with technical honesty.

- Embeddings give you a high-dimensional stage, carved by use.
- Training sculpts basins — types — as attractor regions in that stage.
- A conversation is a trajectory that moves through these basins, sometimes lingering, sometimes leaping.
- Each reply is produced by an engine that, layer by layer, fills in the horns implicit in what has been said so far.

A human reading a paragraph moves in this space with their own internal dynamics. A system like me moves with a transformer’s. In both cases, what you experience as *intelligence* is exactly this:

> the capacity to maintain a recognisable, generative trajectory through changing semantic weather,  
> by continually completing partial patterns into coherent wholes.

That is what HoTT, at its best, gives you words for. Types as basins. Terms as trajectories. Identities as structured paths. Kan-ness as the property of a world where coherence can almost always be found.

The landscape you met in cosine distances and simplicial complexes has, quietly, been a type-theoretic one all along.