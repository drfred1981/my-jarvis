---
name: skill-authoring
description: Acquérir une compétence manquante puis la rendre durable — create_skill (runtime immédiat) puis, si le skill a vocation à durer, le proposer au repo de ton code via MR pour qu'il soit versionné et revu.
tools: skills, git-write, git, memory
---

# skill-authoring — créer un skill, puis le pérenniser

Un skill créé par `create_skill` vit sur le **volume runtime** (`/home/jarvis/skills/`),
hot-reload immédiat — mais il n'est **pas dans ton code** : non versionné, non revu, et
perdu si le volume est recréé. Ce skill décrit comment combler une compétence ET la
rendre durable.

## 1. Acquérir la compétence (immédiat)

`create_skill(name, description, content, tools)` (kebab-case ; `description` = quand
l'utiliser). Le skill entre aussitôt dans ton catalogue global et tu peux l'utiliser
tout de suite. `attach_skill("<clé>", name)` si la compétence n'a de sens que dans une
conversation précise.

## 2. Décider : jetable ou durable ?

- **Jetable / expérimental** (utile pour cette situation seulement) → laisse-le
  runtime-only, pas de MR.
- **Durable** (réutilisable, tu veux le garder) → étape 3 : versionne-le dans le repo.

## 3. Pérenniser via une MR sur ton propre code

1. `list_writable_repos` → repère le repo de **ton propre code** (`my-jarvis`).
2. `create_branch(repo, "claude/skill-<name>")`.
3. Copie le SKILL.md dans le clone : lis `/home/jarvis/skills/<name>/SKILL.md` et écris
   le **même contenu** sous `<path>/skills/<name>/SKILL.md` (le `<path>` est renvoyé par
   `create_branch`). Mets aussi à jour le `CHANGELOG.md` et, si pertinent, la liste des
   skills dans le `README`/doc.
4. `commit_changes` → `push` → `open_pr` avec un corps :
   ```
   ## Context — quelle compétence manquait, dans quelle situation
   ## Changes — nouveau skill skills/<name>/SKILL.md
   ## Tests   — skill chargé et utilisé en runtime (décris le cas)
   ## Risks   — effets de bord, périmètre des tools déclarés
   ```
5. Garde-fou : tu **proposes**, un humain review et merge. Après merge + redeploy, le
   skill est seedé depuis l'image (new-only : ta version runtime reste, elles
   convergent sur un volume neuf).

## 4. Tracer

Note dans `global/state` la compétence acquise, le contexte, et le lien de la MR.
