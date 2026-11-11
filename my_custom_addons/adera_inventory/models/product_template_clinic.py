# -*- coding: utf-8 -*-
from odoo import models, api


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model_create_multi
    def create(self, vals_list):
        """Enforce Lot Tracking and Storable type for clinical medicine and consumables."""
        pharma_xml_ids = [
            "adera_inventory.cat_pharma_pratama",
            "adera_inventory.cat_hemodialysis_hd",
            "adera_inventory.cat_vaccines",
            "adera_inventory.categ_pharma_ethical",
            "adera_inventory.categ_pharma_otc",
            "adera_inventory.categ_bhp_hd_dialyzer",
        ]
        pharma_categ_ids = set()
        for xid in pharma_xml_ids:
            cat = self.env.ref(xid, raise_if_not_found=False)
            if cat:
                pharma_categ_ids.add(cat.id)

        for vals in vals_list:
            categ_id = vals.get("categ_id")
            if categ_id:
                # Check directly or via parent hierarchy
                categ = self.env["product.category"].browse(categ_id)
                is_clinical = (
                    categ.id in pharma_categ_ids
                    or (categ.parent_id and categ.parent_id.id in pharma_categ_ids)
                    or any(c in (categ.name or "") for c in ["PHARMA", "VACCINE", "HEMODIALYSIS", "Farmasi", "Dialyzer"])
                )
                if is_clinical:
                    vals["tracking"] = "lot"
                    vals["is_storable"] = True
                    vals["type"] = "consu"

        return super(ProductTemplate, self).create(vals_list)

    def write(self, vals):
        """When category changes to clinical pharma, ensure lot tracking."""
        categ_id = vals.get("categ_id")
        if categ_id:
            categ = self.env["product.category"].browse(categ_id)
            if any(c in (categ.name or "") for c in ["PHARMA", "VACCINE", "HEMODIALYSIS", "Farmasi", "Dialyzer"]):
                if "tracking" not in vals:
                    vals["tracking"] = "lot"
                if "is_storable" not in vals:
                    vals["is_storable"] = True
        return super(ProductTemplate, self).write(vals)

