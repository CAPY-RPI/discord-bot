from tortoise import fields, models


class FAQModel(models.Model):
    """Tortoise-ORM model for FAQ questions and answers."""

    id = fields.IntField(pk=True)
    question = fields.CharField(max_length=255, unique=True)
    answer = fields.TextField()

    class Meta:
        """Meta configuration for the FAQ model."""

        table = "faqs"
