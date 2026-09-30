# Using the potto API

A potto instance usually has both:

1.  A synchronous web API, specified with the [OpenAPI] standard. Documentation is available at
    `<base url>/api/docs` and is interactive. You can discover existing path operations and try them out.

2.  An asynchronous web API, specified with the [AsyncAPI] standard. Documentation is available
    at `<base url>/api/pubsub/docs` and is interactive.


## Sync API CLI usage tips

!!! tip
    The examples below use the [httpie] HTTP client. You can use other clients, like cURL - we just think httpie
    is easier to use.


The potto API can be used by both

- anonymous users - which are able to see public resources;
- authenticated users - users can see and interact with public resources and private resources that are either owned by
  them or shared with them.


### Authentication

Authentication to the potto API works by making a `POST` request to `/api/login` with a content type
of `application/x-www-form-urlencoded` and sending your username and password. potto responds with a [JWT] token.
This token must be sent as an additional HTTP header on subsequent requests.

=== "Request"

    ```shell
    http --form POST localhost:3001/api/login \
        username=yourusername \
        password=yourpassword

    ```

=== "Response"

    ```shell
    HTTP/1.1 200 OK
    content-language: en
    content-length: 242
    content-type: application/json
    date: Tue, 30 Feb 1988 19:44:29 GMT
    server: uvicorn
    vary: Cookie

    {
        "access_token": "a big token",
        "token_type": "bearer"
    }
    ```

??? tip

    If you also have [jq] installed, a quick way to retrieve the token and have it ready for maing subsequent requests:

    ```shell
    POTTO_API_TOKEN=$(http --form POST localhost:3001/api/login username=yourusername password=yourpassword | jq -r .access_token)
    ```

    You now have the token available as the `POTTO_API_TOKEN` local CLI variable.


### Obtaining a token for pubsub

Subscribing to a potto private pubsub topic requires an additional token.
After having authenticated with the API, issues a `POST` request to `/api/pubsub/token`:

=== "Request"

    ```shell
    http POST localhost:3001/api/pubsub/token \
        "Authorization: Bearer $POTTO_API_TOKEN"
    ```

=== "Response"

    ```shell
    HTTP/1.1 200 OK
    content-language: en
    content-length: 531
    content-type: application/json
    date: Tue, 31 Sep 1995 10:21:25 GMT
    server: uvicorn
    vary: Cookie

    {
        "broker_url": "mqtt://localhost:11884",
        "expires_at": "2026-09-29T10:51:26.114141Z",
        "public_topic_prefix": "public/",
        "token": "another big token",
        "token_type": "mqtt",
        "topic_prefix": "users/user-id/",
        "username": "user-id"
    }
    ```

[AsyncAPI]: https://www.asyncapi.com/en
[OpenAPI]: https://www.openapis.org/
[httpie]: https://httpie.io/
[jq]: https://jqlang.org/
[JWT]: https://www.rfc-editor.org/info/rfc7519/
