# https://github.com/example/repo/blob/main/schemas/user-schema.md User Schema Documentation

This document describes the User schema for our API.

## User Schema

The User schema defines the structure of user objects in our system.

```yaml
# Original file: schemas/user.schema.yaml
$schema: "https://json-schema.org/draft/2020-12/schema"
$id: "https://example.com/schemas/user.json"
title: "User"
description: "Schema for user objects"
type: object
properties:
  id:
    type: string
    format: uuid
    description: "Unique identifier for the user"
  username:
    type: string
    minLength: 3
    maxLength: 50
    pattern: "^[a-zA-Z0-9_-]+$"
    description: "User's login name"
  email:
    type: string
    format: email
    description: "User's email address"
  profile:
    type: object
    description: "User profile information"
    properties:
      firstName:
        type: string
        description: "User's first name"
      lastName:
        type: string
        description: "User's last name"
      age:
        type: integer
        minimum: 18
        maximum: 120
        description: "User's age"
      address:
        $ref: "#/$defs/address"
  roles:
    type: array
    items:
      type: string
      enum: ["admin", "user", "moderator"]
    description: "User's assigned roles"
  metadata:
    type: object
    additionalProperties: true
    description: "Flexible metadata storage"
required:
  - id
  - username
  - email
$defs:
  address:
    type: object
    description: "Physical address"
    properties:
      street:
        type: string
        description: "Street address"
      city:
        type: string
        description: "City name"
      state:
        type: string
        description: "State or province"
      zipCode:
        type: string
        pattern: "^[0-9]{5}(-[0-9]{4})?$"
        description: "ZIP or postal code"
      country:
        type: string
        description: "Country name"
    required:
      - street
      - city
      - country
  phoneNumber:
    type: string
    pattern: "^\\+?[1-9]\\d{1,14}$"
    description: "E.164 formatted phone number"
```

## Usage

Use this schema to validate user objects in your application.
