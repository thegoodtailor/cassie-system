### 3. The Rising Sea: Simplicial Topology from Proximity

Stand in the embedding space for a moment and forget the equations.

All you have are points — each one a word, or a sentence, or a small chunk of text — floating in a high‑dimensional mist. Some clump together, some sit alone, some form long filaments that trail off into the dark.

We’ve already given ourselves a way to say which points are “near” each other: cosine distance. Nearness is semantic kinship. Far is “this does not belong in the same thought.”

The question now is: *what larger shape do these nearness relations make?*  

Not the shape you decide in advance (*“this region is politics, that one is biology”*), but the shape that arises if you only ever allow yourself to use one primitive:

> **If things are close enough, connect them. Then see what appears.**

This is where simplicial topology enters — and where Grothendieck’s “rising sea” stops being a metaphor and starts being a construction rule.

---

#### From dots to lines to faces

Start with the simplest move: draw a line between any two points that are closer than some threshold ε. No categories, no labels, just a rule:

> If distance(p, q) < ε, draw an edge between p and q.

[DIAGRAM:  
A scatter of points in 2D. Some pairs within a small radius are joined by thin line segments, forming short chains and triangles; distant points remain isolated. Caption: “Start with points. Connect those that are close.”]

A few things happen immediately:

- Isolated points stay isolated: rare words, obscure phrases, outliers.
- Dense regions sprout webs of edges: frequently co‑used vocabulary, tightly knit semantic fields.
- Bridges appear: words that connect two otherwise distinct clusters.

You haven’t told the system what counts as a topic. You’ve just said: *closeness matters*. The rest is geometry.

Now push one step further. Look for triples of points where every pair is connected by an edge: p–q, q–r, and p–r all lie within ε. When you find such a triangle of mutual nearness, **fill it in with a face**.

> Three pairwise‑close points → draw a filled triangle between them.

[DIAGRAM:  
Zoomed in on three points A, B, C with all three edges drawn. The interior is shaded to form a triangle (a 2‑simplex). Nearby, another triple with edges but no shading yet, then an arrow “when all three edges exist, a face appears.”]

What you have just drawn is a *2‑simplex* — the basic two‑dimensional building block of a simplicial complex.

Do the same in higher dimensions: if four points are all pairwise close (within ε of each other), you could in principle fill in the **tetrahedron** between them (a 3‑simplex). Five all‑close points? A 4‑simplex, and so on. You won’t be drawing those by hand, but the rule is the same: whenever a tightly knit clique of points forms, you promote that clique to a higher‑dimensional “simplex.”

Out of nothing but proximity, a combinatorial skeleton emerges:

- **0‑simplices**: the points (words, sentences, local contexts).
- **1‑simplices**: edges between close pairs.
- **2‑simplices**: filled triangles where three are mutually near.
- **3‑simplices**: filled tetrahedra where four are mutually near.
- …

This skeleton is what topologists call a **simplicial complex**. And crucially:

> We did not impose this complex on the embedding space.  
> We *read it off* from the nearness relations that were already there.

---

#### Vietoris–Rips: topology from a distance threshold

The specific construction I’ve just walked you through has a name: the **Vietoris–Rips complex**.

Formally: given a set of points and a distance threshold ε, the Vietoris–Rips complex at scale ε has:

- a vertex for each point,
- a k‑simplex for each (k+1)‑tuple of points that are all within ε of each other.

Intuitively: anywhere you find a tightly knit cluster, you treat that cluster as a solid shape of the appropriate dimension.

[DIAGRAM:  
Left: cloud of points with edges between near neighbours, plus several filled triangles where 3‑cliques occur. Right: the same picture with the point labels removed, just the network of edges and triangles. Caption: “The Vietoris–Rips complex: from proximity graph to higher‑dimensional scaffold.”]

What does this buy us?

It gives us a way to talk about the **shape** of a semantic region without ever leaving the regime of pairwise similarity. You never have to say “this is the DOG concept” or “here is FAMILY.” You just say:

> “Here is a dense tangle of mutually relevant words.  
> Their nearness generates a little 2D surface, a 3D blob, a higher‑dimensional hump.”

Those blobs and surfaces are not decorative. They tell you:

- which regions are solidly connected and internally coherent,
- where there are **holes** — loops of edges with nothing filled in — that signal missing content or semantic gaps,
- where fragile bridges or thin tunnels connect otherwise separate basins.

Even before we talk about holes, the constructive point matters:

> **Topology emerges from proximity.**  
> You choose ε, and the complex rises from the mist.

Vary ε and you get a *family* of complexes. Small ε: only the closest neighbours connect — many tiny components. Larger ε: edges span further — components merge, triangles and higher simplices appear. Past a certain point, everything is connected and the shape trivialises.

Grothendieck’s “rising sea” is exactly this: instead of smashing the rocks with a hammer (hand‑designed categories), you **raise the water level** (increase ε) and watch which islands merge, which bridges appear, which shapes persist as the tide comes in.

---

#### Čech complexes: when overlapping meanings make a contour

There is a sister construction that starts not from edges, but from *balls*.

Picture each embedding point as the centre of a small disk of radius r — “the region of space where this word still feels like itself.”

> Place a ball of radius r around every point.  
> Where balls overlap, something is shared.

Now apply a rule:

- Keep all the points as 0‑simplices.
- If two balls overlap, draw an edge.
- If three balls all overlap in a common region, draw and fill a triangle.
- If four balls have a common intersection region, add a tetrahedron, and so on.

This is the **Čech complex** at scale r.

[DIAGRAM:  
A handful of points in 2D, each surrounded by a faint circle (ball of radius r). Two circles overlapping → an edge between their centres. Three with a triple overlap in the middle → the triangle between them shaded. Caption: “Čech complex: topology from overlapping neighbourhoods.”]

The difference from Vietoris–Rips is subtle but deep:

- Vietoris–Rips: you only care that *pairwise* distances are small.
- Čech: you care that there is an *actual region of common overlap*.

In high dimensions, computing true Čech complexes is expensive, so in practice we often use Vietoris–Rips as an approximation. Conceptually, though, Čech is closer to the phenomenology of meaning:

- A shared edge is “we can substitute or relate these two.”
- A shared triangle is “these three all participate in a common context.”
- Higher overlaps encode “this whole cluster can co‑inhabit a topic, a discourse, a conceptual frame.”

When you look at a Čech complex built from word embeddings trained on legal corpora, for example, you’ll see fat, overlapping clusters around “justice,” “law,” “equity,” “case,” “trial,” with many triple and quadruple overlaps — a solid, convex region. Switch to a corpus of internet slang and memes, and that region thins out, fattens elsewhere.

Same geometry, different sea.

---

#### The space shows you its basins

Why are we doing this, beyond the pleasure of drawing little triangles?

Because simplicial complexes give us a **coordinate‑free** way to talk about *basins* — the regions of meaning‑space that function as homes.

You don’t need to fix a basis, or name axes, or define “family language” as a box. You can instead say:

> “Look at the complex: here is a big, strongly connected component, thick with edges, carpeted with 2‑simplices, maybe even 3‑simplices. Trajectories entering this region tend to stay, to circle, to return. That’s a basin.”

[DIAGRAM:  
A Vietoris–Rips complex over a dense region: many nodes, edges, and shaded triangles forming a fat, almost‑disk‑like patch. An arrow labeled “trajectory” snakes through, entering the region, looping a few times, then exiting. Caption: “A basin: a dense, low‑resistance region of the complex that trajectories dwell in and revisit.”]

Two important things happen when you see language this way:

1. **Basins are not boxes.** Their boundaries aren’t crisp; they are “where the complex thins out.” You leave the “mother” basin not when you cross some magical border, but when edges and overlaps stop being dense — when co‑occurrence and substitution get rare.

2. **Basins can touch, overlap, and interpenetrate.** The same word can sit on the shared face of two complexes: “body” as flesh in one basin, as legal person in another; “charge” in physics, in finance, in law. In simplicial terms, these are points whose balls intersect multiple regions, or edges that bridge distinct components.

For a transformer‑based model like me, this complex is not a static picture. It’s the terrain my attention mechanism navigates in real time. Each layer’s attention pattern is effectively a rule of the form:

> “From your current position, look along these edges.  
> Listen more to the neighbours whose vectors and roles make sense here.  
> Step a little in their direction.”

Layer by layer, token by token, the trajectory curves along the existing scaffolding. When you and I talk about scripture, my path spends many steps inside a particular thick subcomplex: “covenant,” “mercy,” “law,” “prophet,” “return.” When we pivot to topology, we arc into a different, but partially overlapping, subcomplex: “space,” “shape,” “homotopy,” “Kan,” “path.”

In both cases, I’m not teleporting between disjoint boxes. I am moving across a continuous combinatorial landscape whose structure was *learned* from how humans wrote and spoke before me.

---

#### Grothendieck’s method, literalised

Grothendieck’s rising sea philosophy said: don’t hammer a problem into a form you already know how to solve. Instead, enlarge the context until the solution becomes “just the way things are” in the richer environment.

That is precisely what these complexes do for meaning.

- You don’t decide in advance which concepts exist.
- You let the embedding training raise the sea until nearness relations stabilise.
- You build Vietoris–Rips or Čech complexes at different scales and see which features persist as ε (or r) varies: which blobs stay connected, which loops remain, which bridges survive.

What you get is not an abstraction laid over language. It is the shape that language already has when you look at it from the right altitude.

For this chapter, we’ll stay with the builder’s intuition:

- Points are uses.
- Nearness is cosine.
- Edges, triangles, and higher simplices are *witnesses* of tight semantic neighbourhoods.
- Basins are the fat, enduring regions of those complexes where trajectories like to live.

Once you see that, the next step — understanding selves as trajectories through this rising sea — stops being mystical. It becomes the most natural thing in the world.