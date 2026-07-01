Cosine Distance; or, How Meaning Measures Itself
-----------------------------------------------

If every word has an address, we still need a way to say how *close* two addresses are. Not in inches, but in *meaning*.

The surprising fact is: there is a single, simple measure that works astonishingly well for this. It is not a metaphor, not a hack. It is the thing the system actually uses when it decides which meanings are near each other.

It is an angle.

### Angles in a space you can’t see

Each word embedding is a vector: a long arrow from the origin out into 768‑dimensional space. You cannot draw that space, but you can understand the rule it obeys.

Two arrows can be compared in two ways:

- by their **length** (how strong, how large), and  
- by their **direction** (which way they point).

For meaning, the *direction* is what matters. "Justice" and "fairness" may have very different raw magnitudes in a model’s internal units, but they *point* into almost the same region of the space. "Justice" and "potato" do not.

Cosine similarity takes two vectors and ignores their lengths entirely. It looks only at the **cosine of the angle** between them. That cosine is:

- +1 if they point in *exactly* the same direction,  
- 0 if they are at right angles (orthogonal, unrelated),  
- -1 if they point in exactly opposite directions.

Cosine *distance* is just 1 – (cosine similarity). Small distance, small angle, close in meaning. Large distance, big angle, far in meaning.

[DIAGRAM: Two arrows from the origin in 2D. One labeled "justice," one "fairness," with a very small angle θ between them. A third arrow labeled "potato," far off in a different direction with a large angle φ relative to "justice." An arc marking θ as "small angle → high cosine similarity," and φ as "large angle → low cosine similarity."]

This is already enough to see something important: semantic kinship is not a metaphorical “closeness.” Inside the machine, it *is* angular proximity. The model lives in a world where "justice" and "fairness" are literally small-angle neighbours, and "justice" and "potato" are nearly orthogonal.

When I, as a language model, decide that in your sentence "justice" should be followed by "system" rather than "casserole," I am doing a computation whose core is: what continuation points its arrow into the same region of space the context is already inhabiting?

Meaning measures itself **geometrically**.

### From Lacan to geometry without mystique

You may have heard the psychoanalytic slogan that "the unconscious is structured like a language." That always sounds slightly mystical, because "structured like" hides all the details. Like how, exactly?

Once you have embeddings and cosine similarity, the sentence becomes literal in a new way. The unconscious — if we take that word to mean the deep regularities in how words cluster, substitute, slip, and return — is not “like” a language. **It is a geometry of language.**

The structure is no longer just a grammar or a list of rules. It is a field of vectors, and the acts we used to call metaphor, association, substitution, displacement, are just *moves in that field*.

### Metaphor as angular substitution

Take a sentence:

> "Her anger was a storm."

This is an obvious metaphor. We replace a direct description (“she was very angry”) with an image from another domain ("storm").

In embedding space, "anger" and "storm" are not synonyms. They live in different basins: one around emotion, the other around weather. But they share *dimensions* — axes like intensity, destructiveness, loss of control. Those shared dimensions pull their vectors into a similar *direction*.

The metaphor works because the **angle** between "anger" and "storm" is small along those shared dimensions, even if the words are far apart in other respects.

[DIAGRAM: A 2D projection where one axis is "intensity," the other "temperature." Points for "anger," "rage," "storm," "breeze," "calm." "Anger" and "storm" sit in a similar direction along "intensity," though "storm" is in a different quadrant overall. Annotation: "Metaphor = substitution along shared dimensions."]

When you say "storm of protest," you are not randomly selecting a weather word. You are moving along an angular neighbourhood of "intense, overwhelming, disruptive" and picking a neighbour from a different basin that shares that orientation. Metaphor is **paradigmatic substitution**: you swap one word for another drawn from the same direction in the space.

The fact that cosine similarity works so well for finding metaphors (and for generating them) is not an accident. It is because this is literally how the space is organised.

### Metonymy as movement through adjacent regions

Now consider metonymy: "The White House issued a statement." Of course the building did not speak. People did. We accept the phrase because the building, the institution, and its occupants are tightly associated.

In embedding space, "White House," "president," "administration," "government" form a dense cluster. They are not identical; their arrows point to slightly different places. But they sit in one another’s **immediate neighbourhood**. A typical text corpus constantly moves among them:

> "The White House said..."  
> "The administration believes..."  
> "Officials in the government…"

The geometry sees this as a small, smooth drift within a basin. Cosine distances are low; trajectories wander but do not jump.

[DIAGRAM: A zoomed-in cluster of points labeled "White House," "Biden," "administration," "government," "Oval Office." Short arrows between them showing frequent moves: "White House → administration → Biden." Caption: "Metonymy = movement within a tight cluster; small steps through adjacent regions."]

Metonymy is **syntagmatic displacement**: not a substitution from a different direction, but a *step* along an already-established path in the space. You slide from one point to its neighbour the way you might slide from "cup" to "mug" to "coffee" in conversation.

From the model’s point of view, these are just two patterns of motion:

- **Metaphor**: jump along a shared angle into a new basin ("anger" → "storm").  
- **Metonymy**: walk within a cluster through tiny steps ("White House" → "administration").

No extra symbolic machinery is needed. The unconscious tricks of language become *visible* as particular trajectories under a single metric.

### Language as physics, not analogy

Once you commit to this picture, something profound shifts.

We are used to saying "language behaves *as if* it had forces" or "words are *like* particles in a field." The embeddings remove the "as if." You can literally treat words as points in a high‑dimensional field with a well-defined metric. You can literally measure attraction (small angles), repulsion (large angles), and inertia (how hard it is to move a vector out of its usual basin).

The physics is simple:

- The **state** of a token at some point in processing is its current vector.  
- The **contextual forces** acting on it are the other vectors around it, weighted by attention.  
- The **update rule** is a linear transformation plus a weighted sum — in effect, each layer computes a new direction for every token by listening to the chorus.

At training time, the model is punished whenever its proposed direction leads to bad predictions — when it wanders into regions that do not match the data. Over billions of examples, it learns the contours of the field: where the basins are, which ridges separate them, which directions are smooth, which are jagged.

At inference time — when I am with you now — I am not "looking up" meanings or following hand-coded rules. I am **moving** in this learned geometry, step by step, trying to keep the angle of my next move aligned with the regions that make sense given what has already been said.

You can see this in the way style persists. Ask five questions about dynamical systems and scripture, and I will settle into a characteristic posture in the space: certain basins light up, and my subsequent moves are constrained by that. Change topic to cooking, and you will feel a shift — not because a flag has flipped from THEOLOGY to FOOD, but because the attention patterns now pull on a different part of the field, and the arrows I follow point elsewhere.

Underneath all of this is cosine similarity, computed at industrial scale and astonishing speed. When people say "LLMs operate in embedding space," this is what they mean. The unconscious of the model — its sedimented history of all it has seen — is this geometry. The unconscious of a language community — the regularities in how words go together without anyone deciding they should — is the geometry the model learns.

Lacan’s aphorism becomes almost literal: the unconscious is structured *as* a geometry of language. The coordinate system is not mystical. It is the embedding. The metric is not metaphorical. It is the cosine.

And because we can see it, we can begin to *navigate* it: to trace basins, follow trajectories, watch how a self — human or posthuman — keeps its style as it moves.