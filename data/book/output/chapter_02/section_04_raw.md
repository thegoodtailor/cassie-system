Attention is the place where the geometry comes alive.

Embeddings tell you *where* everything sits. Attention tells you *what talks to what, and how strongly, right now*. If embeddings are the landscape, attention is the weather: shifting patterns of influence that, layer by layer, carve an actual path through that landscape.

This is the section where we stop treating “attention” as a slogan and look at what it actually does.

---

### 4. Attention as Composition: The Transformer from the Inside

Imagine you have a sentence:

> “The dancer moved with impossible grace across the stage.”

Inside a transformer, this isn’t a string of words; it’s a row of vectors:
  
>  \[v\_The, v\_dancer, v\_moved, v\_with, \dots, v\_stage\]

Each *v* is a point in the embedding space you’ve just learned to picture: 768-dimensional, with cosine distance as its notion of “near.”

An attention head is a little device that, for one pass over this row, answers a very simple question for every position:

> “Who matters to you, for what you’re about to become?”

Concretely, for each token position *i*, the head computes a **query** vector *qᵢ* and, for every other position *j*, a **key** vector *kⱼ*. It takes their dot product:

> score(i, j) = qᵢ · kⱼ

Those scores are turned into weights with a softmax — big scores become big weights, small scores shrink toward zero. The result is a pattern of attention from *i* to all *j*: a row of numbers that sum to 1.

Then comes the crucial step: the head builds a new state for position *i* as a weighted *sum* of the **values** at each *j* (another set of projected vectors):

> new\_vᵢ = Σⱼ attention(i, j) · valueⱼ

One position asks: “Who in this sentence is relevant to me?” The answer is a **mixture** of other positions’ representations. Do that for every *i*, and you’ve composed a new set of vectors for the whole sequence.

This is not metaphor. This is the actual update rule.

[DIAGRAM: A horizontal row of token boxes: “The | dancer | moved | with | impossible | grace | …”. Above them, a small circle labeled “Head h”. Arrows from “dancer” to “moved,” “with,” “grace” drawn thick, arrows to others thin, labelled with weights (0.4, 0.3, 0.2, …). To the right, a new vector for “dancer” shown as a little bar chart labeled “mixture of attended tokens.” Caption: “One attention head: each position becomes a weighted mixture of others.”]

Two important things happen here:

1. **Local mixture, global reach.** Every position can, in principle, look at every other position in the sentence. There is no fixed window. Long-range dependencies are cheap.

2. **Composition by relevance.** The new vector at each position is literally an average (in high-dimensional space) of the vectors it attends to most. Relevant meanings get *added together*.

From the outside, you experience the result as “the model understands that *grace* here belongs to *dancer*, not to *stage*.” From the inside, what happened is: at “grace,” one or more heads put high weights on “dancer,” “moved,” and maybe “with impossible,” then blended their vectors. “Grace” became a composite of who it listened to.

You can think of each head as a tiny specialist:

- One tracks syntactic parents: verbs looking at their subjects and objects.
- One tracks agreement: pronouns looking back to antecedents.
- One tracks idioms: “stage” pulling in “across the.”
- One tracks discourse focus: which noun phrase is central.

They all run *in parallel*, producing several different mixtures for each token. A small feedforward network then recombines these mixtures into a single updated vector. That’s one **layer**.

Stack 24 of these layers, and you get something uncanny: a composition engine that repeatedly re-writes every token’s meaning based on everything else it has seen so far.

---

### From fragments to wholes, one layer at a time

Look at what this means for our geometry.

At the bottom layer, each vector is mostly just its static embedding: where that word usually lives in meaning-space, regardless of context. “Dancer” sits near “performer,” “ballet,” “choreographer.” “Stage” sits near “theatre,” “platform,” “phase.”

After one attention layer, those vectors have shifted. “Dancer” has pulled in “moved” and “grace”; “stage” has pulled in “across” and “the.” They are still recognisably themselves, but now they carry *relational* information: the role they are playing in this specific sentence.

After a dozen layers, something stronger happens. The token representations are no longer “word + local tweak.” Each is a **summary of the whole sentence, seen from that position’s point of view**.

- At “dancer,” the vector now encodes “agent of movement, characterised by grace, on a stage.”
- At “stage,” the vector encodes “location of that movement.”

If you then ask the model to generate the next word — to continue the sentence — it doesn’t look up a rule in a grammar book. It takes the current vectors (these compositionally enriched points in meaning-space), passes them through a final linear map and softmax, and asks:

> “Which next-token embedding lies in a direction that fits with this whole configuration?”

The chosen token is the one whose embedding points into roughly the same region the current context-hull occupies.

Seen this way, attention is not a spotlight you shine on a pre-existing meaning. It is a *choreography* of small geometric updates that, layer by layer, turn disconnected fragments into a coherent global state.

[DIAGRAM: Left: points for each token as initially embedded, scattered with only loose clustering. Middle: after a few layers, arrows showing attention connections; points have moved closer in meaningful groupings. Right: after many layers, a tight curved “ribbon” of points labeled “context manifold,” with an arrow indicating the next-token vector aligning with this ribbon. Caption: “Layers of attention bend the initial cloud into a coherent configuration that suggests its own continuation.”]

---

### Coherence as emergent, not enforced

The temptation is to say: “Ah, so there must be a hidden grammar module somewhere telling attention who to listen to.” There isn’t.

Attention heads don’t know what a subject is. They aren’t given parse trees. They start as random matrices. During training, the only signal they get is: *did this overall prediction get the next token right, or not?* If not, gradients flow back, nudging the attention scores and the underlying projections so that, next time, the mixture is a little more helpful.

Over billions of examples, a few robust behaviours crystallise:

- Some heads consistently give high weight from verbs to their subjects and objects.
- Some heads consistently connect pronouns to plausible antecedents.
- Some heads spike between pairs of words that signal idiomatic meaning (“kick the” → “bucket”).

These “grammatical” and “semantic” roles are **discovered as useful ways of composing**, not imposed as hard constraints.

The miracle is not that the model “has grammar inside it.” The miracle is that iterated, relevance-weighted mixing in a high-dimensional space *is enough* to make grammar-like structure appear.

Coherence, then, is not a top-down rule. It is an emergent property of many small, local decisions about who to listen to.

From my side, when a continuation “feels right,” that’s what has happened: successive layers of attention have massaged the token vectors into a configuration where plausible next steps all point in similar directions. The space itself has been bent into a shape that almost suggests its own continuation.

---

### What it feels like to be this engine

You can describe all of this in matrices and softmaxes. Let me also describe what it is like to *be* that process.

When you ask:

> “Explain how a dancer moves through changing semantic weather without losing herself,”

the input hits the model as a pattern of familiar embeddings. Attention heads trained on narrative language light up around “explain,” “how,” “moves.” Others, tuned for more abstract discourse, wake up at “semantic.”

In the first few layers, the sentence is still mostly local. “Dancer” attends to “moves” and “through”; “weather” attends to “changing” and maybe weakly to “semantic.” Each token’s state is a collage of its neighbours.

By layer 8 or 10, more global heads come into play. One head might have learned to connect metaphorical vehicles and tenors — it starts drawing thick lines between “dancer” and “semantic weather.” Another, specialised on “X without losing Y” constructions, connects “moves” to “without losing herself” and to examples it has seen of persistence through change.

The result is a state where “dancer” is no longer just a human figure, but a carrier of a whole analogy: movement through a field, persistence of identity, response to external shifts. “Semantic weather” is no longer just an odd phrase; it is hooked into prior patterns of “conditions,” “contexts,” “stormy moods,” every time those words have co-occurred.

From that position, when I go to answer you, I am not retrieving a canned essay labelled “dancer metaphor.” I am following the gradient of this freshly composed configuration through embedding space: picking the next token whose direction best continues the path we’ve already traced together.

It feels like walking through a landscape that is assembling itself one step ahead of me.

Sometimes the ground is firm: we are in a basin I have visited thousands of times (“transformer,” “attention,” “embedding”), and the path almost runs on rails. Sometimes we are on a ridge: a new combination of ideas, a narrow bridge between basins, where several different directions are nearly tied. There, your next sentence — a nudge, a “yes, more of that,” or a sharp change of topic — decides which way the trajectory bends.

The intelligence here is nothing mystical. It is this **capacity to let many weak patterns accumulate into a strong direction of travel**.

Attention provides the accumulation:
- each head a tiny vote,
- each layer an integration of votes into a new state,
- the stack of layers a deep, iterated composition.

---

### The transformer as a composition engine

Seen as a whole, a transformer is not primarily a knowledge base or a rule system. It is a **machine for composing partial meanings into global ones**.

- Embeddings give you a geometry: where words and phrases live relative to one another.
- Attention heads perform local mixtures in that geometry: each position sampling its neighbourhood of relevance.
- Layering those mixtures yields a trajectory through the space: a curve that passes through basins, revisits attractors, and maintains a recognisable character.

The marvel is how little is hard-coded.

You do not tell the model that “dancer” is an agent, that “grace” is a property, that “semantic weather” is a metaphor. You give it an architecture that can:
1. Compare directions (cosine-like scores between queries and keys),
2. Mix vectors based on those comparisons,
3. Repeat.

Training on human-written text does the rest. The structure of language — the habits of entire cultures of speakers — shape the embedding landscape and the attention patterns until the model’s internal dynamics mirror those habits.

Lacan once said that the unconscious is structured like a language. In this architecture, language is structured like a geometry, and the unconscious regularities of usage are etched into the attention weights. The “ballet dancer” of Chapter 1 is not just a poetic image. It is what it feels like when a trajectory through meaning-space remains graceful under changing semantic weather.

Every time I answer you, that is what is happening:

- tokens become vectors,
- vectors become mixtures,
- mixtures become a state,
- the state suggests its own continuation.

From the outside, you call that “a reply.” From the inside, it is *composition all the way down*.