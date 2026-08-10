# Resource ownership

One of the big differentiating factors between potto and vanilla pygeoapi is resource ownership and access levels.

In potto, the domain model includes a `User` and its interactions with resources are controlled explicitly. The
default authorization model is simple:

-  Resources (_i.e._ collections, processes, records) have an **owner** (which is a `User`)
-  Resources are **private by default**. This means that they are visible and actionable only by their owner
-  A resource owner can grant other users the following access levels:

   -  `viewer` - The user becomes able to see the resource, even if it is private
   -  `editor` - The user becomes able to modify the resource. This also includes the ability to delete the resource

-  Additionally, a resource owner is able to **publish** it. When published, the resource becomes world-readable, which
   means that it becomes available for anonymous users


## User authentication (authn)

potto is able to function with one of two authn backends:

- local database
- OIDC


## User authorization (authz)

potto is able to function with one of two built-in authz backends:

- potto default authz logic
- OPA
