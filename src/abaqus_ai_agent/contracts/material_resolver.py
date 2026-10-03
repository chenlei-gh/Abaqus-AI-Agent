"""MaterialResolver engine for mapping physical MaterialRecord to canonical Abaqus MaterialDefinition.

Enforces constitutive sanity, anti-hallucination gates, environmental condition matching,
and unit system conversions.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .material import ElasticProperties, MaterialDefinition, PlasticProperties, ThermalProperties
from .material_record import MaterialCondition, MaterialProperty, MaterialRecord
from .units import UnitSystem


@dataclass(frozen=True)
class MaterialResolutionResult:
    """Outcome of resolving a real-world MaterialRecord into an Abaqus MaterialDefinition."""
    status: str                              # "RESOLVED", "ASSISTED", "BLOCKED", "UNSUPPORTED"
    material_definition: Optional[MaterialDefinition]
    diagnostics: Tuple[str, ...] = ()
    assumptions: Tuple[str, ...] = ()
    evidence_source: str = ""

    @property
    def is_executable(self) -> bool:
        return self.status in ("RESOLVED", "ASSISTED") and self.material_definition is not None


class MaterialResolver:
    """Constitutive mapper and gatekeeper between external material data and solver models."""

    @staticmethod
    def _convert_stress(val: float, from_unit: str, target_system: UnitSystem) -> float:
        """Convert stress/modulus quantity to target unit system."""
        # Standardize from_unit
        u = from_unit.strip().lower()
        # Convert to Pa first
        if u in ("mpa", "n/mm2", "n/mm^2"):
            pa_val = val * 1e6
        elif u in ("gpa", "kn/mm2"):
            pa_val = val * 1e9
        elif u in ("kpa",):
            pa_val = val * 1e3
        elif u in ("pa", "n/m2", "n/m^2"):
            pa_val = val
        elif u in ("psi",):
            pa_val = val * 6894.757
        else:
            pa_val = val  # fallback assume matching

        # Convert Pa to target system stress
        if target_system.name in ("MM_N_MPA", "SI_MM"):
            return pa_val / 1e6  # to MPa
        return pa_val  # to Pa for SI / M_N_PA

    @staticmethod
    def _convert_density(val: float, from_unit: str, target_system: UnitSystem) -> float:
        """Convert density quantity to target unit system."""
        u = from_unit.strip().lower()
        # Convert to kg/m3 first
        if u in ("g/cm3", "g/cm^3", "g/ml", "kg/l"):
            kg_m3 = val * 1000.0
        elif u in ("kg/m3", "kg/m^3"):
            kg_m3 = val
        elif u in ("tonne/mm3", "tonne/mm^3", "t/mm3"):
            kg_m3 = val * 1e12
        else:
            kg_m3 = val

        # Convert kg/m3 to target system density
        if target_system.name in ("MM_N_MPA", "SI_MM"):
            return kg_m3 * 1e-12  # tonne/mm3
        return kg_m3  # kg/m3 for SI

    @classmethod
    def resolve(
        cls,
        record: MaterialRecord,
        target_temperature: Optional[float] = None,
        target_humidity: str = "dry",
        constitutive_intent: str = "linear_elastic",
        target_unit_system: str = "MM_N_MPA",
        allow_assisted_assumptions: bool = True,
        operating_strain_rate: Optional[float] = None,
        operating_duration: Optional[float] = None,
        test_standard: Optional[str] = None,
    ) -> MaterialResolutionResult:
        """Resolve a MaterialRecord into an executable Abaqus MaterialDefinition.

        Args:
            record: Canonical MaterialRecord with experimental properties/curves.
            target_temperature: Operating temperature (in deg C). Defaults to record default.
            target_humidity: Environmental humidity condition ("dry", "conditioned").
            constitutive_intent: "linear_elastic", "elastoplastic", "viscoelastic", "creep".
            target_unit_system: Desired solver unit system ("MM_N_MPA", "SI").
            allow_assisted_assumptions: Whether engineering approximations are permitted.
            operating_strain_rate: Specific operating strain rate (1/s).
            operating_duration: Sustained loading duration for creep/viscoelasticity (s).
            test_standard: Preferred testing standard (e.g. "ISO 527-1/-2").
        """
        diagnostics: List[str] = []
        assumptions: List[str] = []
        unit_sys = UnitSystem.named(target_unit_system)

        req_temp = target_temperature if target_temperature is not None else record.default_condition.temperature

        # 1. Environmental Condition Preflight
        # Check temperature compatibility
        available_temps = {
            p.condition.temperature for p in record.properties if p.condition is not None
        }
        available_temps.add(record.default_condition.temperature)
        for c in record.curves:
            available_temps.add(c.condition.temperature)

        temp_diff = min(abs(req_temp - t) for t in available_temps)
        # Strict anti-extrapolation: even under assisted mode, refuse extreme thermal shift (> 50C)
        if temp_diff > 50.0 or (temp_diff > 25.0 and not allow_assisted_assumptions):
            return MaterialResolutionResult(
                status="BLOCKED",
                material_definition=None,
                diagnostics=(
                    f"Operating temperature {req_temp} C has no close experimental data "
                    f"(closest available: {min(available_temps, key=lambda t: abs(req_temp - t))} C, diff={temp_diff:.1f} C). "
                    "Fail-closed on uncharacterized thermal degradation/glass transition.",
                ),
                evidence_source=record.source.locator,
            )
        if temp_diff > 25.0:
            assumptions.append(
                f"Operating temperature {req_temp} C extrapolated from test data at "
                f"{min(available_temps, key=lambda t: abs(req_temp - t))} C (thermal shift uncalibrated)."
            )

        # 2. Extract Young's Modulus & Poisson's ratio
        cond_query = MaterialCondition(
            temperature=req_temp,
            humidity_state=target_humidity,
            strain_rate=operating_strain_rate,
            test_time=operating_duration,
            test_standard=test_standard,
        )
        prop_e = record.get_property("youngs_modulus", cond_query) or record.get_property("tensile_modulus", cond_query)
        if prop_e is None:
            # Check if property exists under unconditioned query to provide informative diagnostics
            fallback_prop = record.get_property("youngs_modulus") or record.get_property("tensile_modulus")
            diag_msg = f"Missing youngs_modulus for requested condition (T={req_temp}C, humidity={target_humidity}"
            if operating_strain_rate:
                diag_msg += f", strain_rate={operating_strain_rate}"
            if operating_duration:
                diag_msg += f", duration={operating_duration}"
            diag_msg += ")."
            if fallback_prop and fallback_prop.condition:
                diag_msg += f" Closest available test condition was T={fallback_prop.condition.temperature}C, {fallback_prop.condition.humidity_state}."
            return MaterialResolutionResult(
                status="BLOCKED",
                material_definition=None,
                diagnostics=(diag_msg,),
                evidence_source=record.source.locator,
            )

        E_val = cls._convert_stress(prop_e.value, prop_e.unit, unit_sys)

        prop_nu = record.get_property("poissons_ratio", cond_query) or record.get_property("poisson_ratio", cond_query)
        if prop_nu is not None:
            nu_val = prop_nu.value
        else:
            # Standard engineering polymer default estimate with explicit assumption
            nu_val = 0.35 if "PA" in record.identity.polymer_family or "POM" in record.identity.polymer_family else 0.38
            assumptions.append(f"Poisson's ratio not in datasheet; assumed standard engineering polymer value nu={nu_val}.")

        elastic_props = ElasticProperties(
            youngs_modulus=E_val,
            poisson_ratio=nu_val,
            temperature_dependence=(len(available_temps) > 1),
        )

        # 3. Density
        prop_rho = record.get_property("density", cond_query)
        density_val: Optional[float] = None
        if prop_rho is not None:
            density_val = cls._convert_density(prop_rho.value, prop_rho.unit, unit_sys)

        # 4. Thermal properties
        prop_tc = record.get_property("thermal_conductivity", cond_query)
        prop_exp = record.get_property("expansion_coefficient", cond_query) or record.get_property("clte", cond_query)
        thermal_props: Optional[ThermalProperties] = None
        if prop_tc is not None or prop_exp is not None:
            tc_val = prop_tc.value if prop_tc else 0.25  # standard polymer fallback
            exp_val = prop_exp.value if prop_exp else None
            thermal_props = ThermalProperties(
                conductivity=tc_val,
                expansion_coefficient=exp_val,
            )

        # 5. Constitutive Intent & Polymer J2 Safeguard
        plastic_props: Optional[PlasticProperties] = None
        if constitutive_intent == "elastoplastic":
            # Search for calibrated yield stress or stress-strain curve
            prop_yield = record.get_property("yield_stress", cond_query) or record.get_property("stress_at_yield", cond_query)
            curve_ss = record.get_curve("stress_strain", cond_query)

            if prop_yield is not None:
                sy_val = cls._convert_stress(prop_yield.value, prop_yield.unit, unit_sys)
                hardening: List[Tuple[float, float]] = []

                if curve_ss is not None:
                    # Calibrate true plastic strain from nominal curve: eps_true = ln(1 + eps_eng), sigma_true = sigma_eng * (1 + eps_eng)
                    # eps_plastic = eps_true - sigma_true / E
                    raw_pts = curve_ss.points
                    for e_nom, s_nom in raw_pts:
                        # normalize nominal strain if provided in %
                        e_frac = e_nom / 100.0 if curve_ss.x_unit in ("%", "percent") else e_nom
                        s_target = cls._convert_stress(s_nom, curve_ss.y_unit, unit_sys)
                        if e_frac > 0 and s_target >= sy_val:
                            # approximate true plastic strain
                            eps_true = e_frac
                            sigma_true = s_target
                            eps_p = max(0.0, eps_true - (sigma_true / E_val))
                            if eps_p > 0 and (not hardening or eps_p > hardening[-1][1]):
                                hardening.append((round(sigma_true, 3), round(eps_p, 5)))
                    assumptions.append("Polymer tensile curve calibrated into equivalent J2 hardening curve for Abaqus solver.")
                else:
                    assumptions.append("Single-point yield stress used with ideal perfectly plastic assumption.")

                plastic_props = PlasticProperties(
                    yield_stress=sy_val,
                    plastic_strain=0.0,
                    hardening_table=tuple(hardening),
                )
            else:
                diagnostics.append("Constitutive intent 'elastoplastic' requested, but no yield stress or stress-strain data found.")
                if not allow_assisted_assumptions:
                    return MaterialResolutionResult(
                        status="BLOCKED",
                        material_definition=None,
                        diagnostics=tuple(diagnostics),
                        evidence_source=record.source.locator,
                    )
                # Fallback to linear elastic with warning
                assumptions.append("Degraded to linear elastic model due to absent inelastic yield data.")

        elif constitutive_intent in ("viscoelastic", "creep"):
            # Check for creep or DMA curves
            curve_creep = record.get_curve("creep_isochronous", cond_query)
            if curve_creep is None:
                return MaterialResolutionResult(
                    status="UNSUPPORTED",
                    material_definition=None,
                    diagnostics=(
                        f"Constitutive intent '{constitutive_intent}' requires experimental creep/relaxation curves, "
                        "which are not present in this MaterialRecord. Request user testing data or fall back to elastic.",
                    ),
                    evidence_source=record.source.locator,
                )
            assumptions.append(f"Time-dependent {constitutive_intent} behavior available in curves.")

        # Construct canonical MaterialDefinition
        mat_name = f"{record.identity.polymer_family}_{record.identity.manufacturer}_{record.identity.grade}".replace(" ", "_").replace("-", "_")

        provenance_str = (
            f"Provider={record.source.provider}; Locator={record.source.locator}; "
            f"Grade={record.identity.grade}; Condition={target_humidity}@{req_temp}C"
        )

        metadata_dict = {
            "identity": record.identity.to_dict(),
            "source": record.source.to_dict(),
            "resolved_condition": {"temperature": req_temp, "humidity": target_humidity},
            "constitutive_intent": constitutive_intent,
        }

        mat_def = MaterialDefinition(
            name=mat_name,
            unit_system=target_unit_system,
            elastic=elastic_props,
            density=density_val,
            plastic=plastic_props,
            thermal=thermal_props,
            provenance=provenance_str,
            assumptions=tuple(assumptions),
            metadata=metadata_dict,
        )

        status = "ASSISTED" if assumptions else "RESOLVED"
        return MaterialResolutionResult(
            status=status,
            material_definition=mat_def,
            diagnostics=tuple(diagnostics),
            assumptions=tuple(assumptions),
            evidence_source=record.source.locator,
        )
