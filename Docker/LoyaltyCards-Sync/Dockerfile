# ---- build ----
FROM golang:1.25-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /pb/loyaltycards-sync .

# ---- runtime ----
FROM alpine:3.20
RUN apk add --no-cache ca-certificates
WORKDIR /pb
COPY --from=build /pb/loyaltycards-sync /pb/loyaltycards-sync
RUN adduser -D -H -u 10001 app && mkdir -p /pb/pb_data && chown -R app:app /pb
USER app
EXPOSE 8090
ENTRYPOINT ["/pb/loyaltycards-sync", "serve", "--http=0.0.0.0:8090"]
